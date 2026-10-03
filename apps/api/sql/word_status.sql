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
-- on both tables. Forms of an invalid root, and invalid forms, are left out of
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

-- The word cache. Same signature and grants as before; the only change is that
-- an invalid form, or any form of an invalid root, no longer reaches the cache.
-- The root itself is still returned, so the add path finds it by name instead
-- of creating it again.
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
      and (last_fetched_word_id is null or w.id > last_fetched_word_id)
    order by w.id asc
    limit fetch_limit
  )
  select sw.word_id, sw.word, wf.form as wordform
  from selected_words sw
  left join wordforms wf
    on sw.word_id = wf.word_id
   and (wf.flagged is null or wf.flagged = false)
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
