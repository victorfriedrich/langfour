-- word status: one audit verdict per root and per form, replacing `flagged`
-- and `cognate`.
--
-- Before: `words.flagged` was mostly false alarms (everyday words like
-- "el coche"), `words.cognate = 'invalid'` was about half right, and the word
-- cache ignored both on roots, so junk roots kept linking. `cognate` holds no
-- value other than 'invalid' in any language.
--
-- After: `status` is one of
--   unverified  not audited yet (the default)
--   valid       Jev is confident it is a real word in dictionary form
--   flagged     Jev is unsure; Claude reviews these and sets valid/invalid
--   invalid     not a word of the language
-- on both tables. Invalid roots, their forms, and invalid forms are left out of
-- the word cache; everything else still links. `flagged` and `cognate` stay
-- until every reader has moved to `status`, then they are dropped.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector. The deployed
-- database is the source of truth; this file is the runbook and the review
-- artifact. Idempotent: safe to re-run.

alter table public.words
    add column if not exists status text not null default 'unverified',
    add column if not exists status_reason text,
    add column if not exists audit jsonb,          -- the audit's raw probabilities
    add column if not exists audited_at timestamptz;

alter table public.wordforms
    add column if not exists status text not null default 'unverified',
    add column if not exists status_reason text,
    add column if not exists audit_score real;     -- P(form belongs to its root)

do $$ begin
    alter table public.words add constraint words_status_check
        check (status in ('unverified', 'valid', 'flagged', 'invalid'));
exception when duplicate_object then null; end $$;

do $$ begin
    alter table public.wordforms add constraint wordforms_status_check
        check (status in ('unverified', 'valid', 'flagged', 'invalid'));
exception when duplicate_object then null; end $$;

-- The word cache. Invalid roots must not shadow a valid root's forms after a
-- merge. The add path checks existing roots separately, including invalid ones,
-- to avoid recreating rejected entries. Same signature and grants as before.
create or replace function public.get_words_with_wordforms_cursor(
    language_param text,
    last_fetched_word_id integer default null,
    fetch_limit integer default 10)
returns table(word_id integer, word text, wordform text)
language plpgsql
as $$
begin
  return query
  with selected_words as (
    select w.id as word_id, w.root as word, w.status as word_status
    from words w
    where w.language = language_param
      and w.status <> 'invalid'
      and (last_fetched_word_id is null or w.id > last_fetched_word_id)
    order by w.id asc
    limit fetch_limit
  )
  select sw.word_id, sw.word, wf.form as wordform
  from selected_words sw
  left join wordforms wf
    on sw.word_id = wf.word_id
   and wf.status <> 'invalid'
   and sw.word_status <> 'invalid'
  order by sw.word_id asc;
end;
$$;

-- Bulk write for scripts/audit_words.py: one call per batch instead of one
-- request per row. Service role only.
create or replace function public.apply_word_audit(words_payload jsonb, forms_payload jsonb)
returns void
language sql
set search_path = public
as $$
  update public.words w
     set status = x.status, status_reason = x.status_reason, audit = x.audit, audited_at = now()
    from jsonb_to_recordset(words_payload) as x(id integer, status text, status_reason text, audit jsonb)
   where w.id = x.id;
  update public.wordforms f
     set status = y.status, status_reason = y.status_reason, audit_score = y.score
    from jsonb_to_recordset(forms_payload) as y(id integer, status text, status_reason text, score real)
   where f.id = y.id;
$$;

revoke all on function public.apply_word_audit(jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.apply_word_audit(jsonb, jsonb) to service_role;

-- Merge a root into the root it should have been, for scripts/review_flagged.py.
-- The source's forms move to the target unless the target already has them
-- (wordforms is unique on (word_id, form)). The source's own bare word becomes a
-- form of the target only when the source has no forms: then it is the word
-- seen in transcripts (sacaran -> sacar). A source with forms has a root that is
-- only a label (el milk: leche), which must not become Spanish. User rows move
-- to the target with their RemNote notes and tests. A user who already has the
-- target keeps that row: it becomes known if the source was, takes the source's
-- review progress if further along, and gets the source's tests and RemNote note.
-- The source row is then deleted, unless the user has a note on both (two Rems
-- for one word); that row stays so its Rem keeps syncing. The source is left
-- invalid.
create or replace function public.merge_roots(payload jsonb)
returns integer
language plpgsql
set search_path = public
as $$
declare m record; merged integer := 0; had_forms boolean; moved uuid[];
begin
  for m in select * from jsonb_to_recordset(payload) as x(src integer, dst integer, reason text) loop
    continue when m.src = m.dst;
    had_forms := exists (select 1 from wordforms where word_id = m.src);
    update wordforms f set word_id = m.dst
     where f.word_id = m.src
       and not exists (select 1 from wordforms g where g.word_id = m.dst and g.form = f.form);
    delete from wordforms where word_id = m.src;
    if not had_forms then
      insert into wordforms (word_id, form, status)
      select m.dst, lower(regexp_replace(w.root, '^(el|la|los|las|el/la) ', '')), 'valid'
        from words w where w.id = m.src
      on conflict (word_id, form) do nothing;
    end if;
    select coalesce(array_agg(u.user_id), '{}') into moved from userwords u
     where u.word_id = m.src
       and not exists (select 1 from userwords d where d.user_id = u.user_id and d.word_id = m.dst);
    insert into userwords (user_id, word_id, status, source, created_at, last_reviewed_at,
                           next_review_due_at, ease_factor, repetition, interval_days)
    select user_id, m.dst, status, source, created_at, last_reviewed_at,
           next_review_due_at, ease_factor, repetition, interval_days
      from userwords where word_id = m.src and user_id = any(moved);
    update srs_notes set word_id = m.dst where word_id = m.src and user_id = any(moved);
    update flashcardtests set word_id = m.dst where word_id = m.src and user_id = any(moved);
    delete from userwords where word_id = m.src and user_id = any(moved);
    -- Users who already had the target.
    update srs_notes s set word_id = m.dst
     where s.word_id = m.src
       and not exists (select 1 from srs_notes t
                        where t.user_id = s.user_id and t.provider = s.provider and t.word_id = m.dst);
    update userwords d set status = 'known'
      from userwords s
     where s.word_id = m.src and s.user_id = d.user_id and d.word_id = m.dst
       and s.status = 'known' and d.status = 'learning';
    update userwords d set last_reviewed_at = s.last_reviewed_at, next_review_due_at = s.next_review_due_at,
           ease_factor = s.ease_factor, repetition = s.repetition, interval_days = s.interval_days
      from userwords s
     where s.word_id = m.src and s.user_id = d.user_id and d.word_id = m.dst
       and coalesce(s.repetition, 0) > coalesce(d.repetition, 0);
    update flashcardtests set word_id = m.dst where word_id = m.src;
    delete from userwords u
     where u.word_id = m.src
       and not exists (select 1 from srs_notes s where s.user_id = u.user_id and s.word_id = m.src);
    update words set status = 'invalid', status_reason = m.reason where id = m.src;
    merged := merged + 1;
  end loop;
  return merged;
end;
$$;

revoke all on function public.merge_roots(jsonb) from public, anon, authenticated;
grant execute on function public.merge_roots(jsonb) to service_role;
