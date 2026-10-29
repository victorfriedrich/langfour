-- Langfour as a flashcard provider, like RemNote
-- (docs/plans/learner-word-data-model.md, step 3).
--
-- Langfour schedules reviews itself; RemNote, and maybe later Anki, are
-- optional apps a user can connect. Until now Langfour's schedule lived in
-- five SM-2 columns on userwords and its reviews in flashcardtests, apart from
-- the srs_* tables RemNote uses, so every reader had to combine the two. Here
-- Langfour becomes provider 'langfour' in those same tables:
--
--   srs_notes     one Langfour note per word, external_id null
--   srs_cards     one 'forward' card per note; external_id = 'forward' (the
--                 column is the card's id within its note; Langfour has no
--                 outside id)
--   srs_card_sm2  ease, repetition and interval of a Langfour card; the due
--                 date is srs_cards.next_due_at, as for RemNote
--   srs_reviews   right answers as 'good', wrong as 'again'
--
-- Langfour is the base scheduler: every learning word has a Langfour card,
-- whatever else is connected, so disconnecting RemNote needs no migration (the
-- Langfour schedule takes over; srs_carry_over_due copies RemNote's due dates
-- across first). userdata.review_provider says which scheduler is active.
--
-- The SM-2 columns on userwords and the flashcardtests table stay for now,
-- unread: dropped once the app has run on this for a while.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, after
-- remnote_sync.sql. Then re-apply known_words.sql, word_progress.sql,
-- word_events.sql (get_user_counts_with_wordforms) and word_status.sql
-- (merge_roots), whose functions now read the srs_* tables. Idempotent.

-- ---------------------------------------------------------------------------
-- Langfour notes: provider 'langfour', no outside id.
-- ---------------------------------------------------------------------------
alter table public.srs_notes drop constraint if exists srs_notes_provider_check;
alter table public.srs_notes add constraint srs_notes_provider_check
    check (provider in ('remnote', 'langfour'));

alter table public.srs_notes alter column external_id drop not null;
alter table public.srs_notes drop constraint if exists srs_notes_external_id_check;
alter table public.srs_notes add constraint srs_notes_external_id_check
    check (provider = 'langfour' or external_id is not null);

create table if not exists public.srs_card_sm2 (
    card_id       bigint primary key references public.srs_cards (id) on delete cascade,
    ease_factor   numeric not null default 2.5,
    repetition    integer not null default 0,
    interval_days integer not null default 1
);

alter table public.srs_card_sm2 enable row level security;

drop policy if exists srs_card_sm2_select_own on public.srs_card_sm2;
create policy srs_card_sm2_select_own on public.srs_card_sm2
    for select to authenticated
    using (exists (select 1 from public.srs_cards c
                   join public.srs_notes n on n.id = c.note_id
                   where c.id = card_id and n.user_id = (select auth.uid())));

revoke insert, update, delete, truncate on public.srs_card_sm2 from anon, authenticated;

-- ---------------------------------------------------------------------------
-- The Langfour card of a user's word, created if missing (due at p_due).
-- Security definer because only the API writes srs_* tables; called by the
-- trigger below and by the review function, never by clients directly.
-- ---------------------------------------------------------------------------
create or replace function public.srs_langfour_card(p_user_id uuid, p_word_id integer,
                                                    p_due timestamptz default now())
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare v_note bigint; v_card bigint;
begin
    insert into public.srs_notes (user_id, word_id, provider)
    values (p_user_id, p_word_id, 'langfour')
    on conflict (user_id, provider, word_id) do nothing;
    select id into v_note from public.srs_notes
     where user_id = p_user_id and word_id = p_word_id and provider = 'langfour';

    insert into public.srs_cards (note_id, external_id, kind, next_due_at)
    values (v_note, 'forward', 'forward', p_due)
    on conflict (note_id, external_id) do nothing;
    select id into v_card from public.srs_cards where note_id = v_note and external_id = 'forward';

    insert into public.srs_card_sm2 (card_id) values (v_card) on conflict do nothing;
    return v_card;
end;
$$;

revoke execute on function public.srs_langfour_card(uuid, integer, timestamptz) from public, anon, authenticated;
grant execute on function public.srs_langfour_card(uuid, integer, timestamptz) to service_role;

-- Every word that becomes a learning word gets its Langfour card, whatever
-- path saved it (extension, imports, onboarding, the web app) and whichever
-- scheduler the user has.
create or replace function public.srs_langfour_card_for_word()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.status = 'learning' then
        perform public.srs_langfour_card(new.user_id, new.word_id,
                                         coalesce(new.next_review_due_at at time zone 'utc', now()));
    end if;
    return new;
end;
$$;

revoke execute on function public.srs_langfour_card_for_word() from public, anon, authenticated;

drop trigger if exists userwords_langfour_card on public.userwords;
create trigger userwords_langfour_card
    after insert or update of status on public.userwords
    for each row execute function public.srs_langfour_card_for_word();

-- ---------------------------------------------------------------------------
-- Backfill. Words that are learning or disabled (their schedule is kept), and
-- known words with Langfour review history, so none of it is left behind.
-- ---------------------------------------------------------------------------
insert into public.srs_notes (user_id, word_id, provider)
select uw.user_id, uw.word_id, 'langfour'
from public.userwords uw
where uw.status in ('learning', 'disabled')
   or exists (select 1 from public.flashcardtests ft
              where ft.user_id = uw.user_id and ft.word_id = uw.word_id)
on conflict (user_id, provider, word_id) do nothing;

insert into public.srs_cards (note_id, external_id, kind, next_due_at)
select n.id, 'forward', 'forward', uw.next_review_due_at at time zone 'utc'
from public.srs_notes n
join public.userwords uw on uw.user_id = n.user_id and uw.word_id = n.word_id
where n.provider = 'langfour'
on conflict (note_id, external_id) do nothing;

insert into public.srs_card_sm2 (card_id, ease_factor, repetition, interval_days)
select c.id, coalesce(uw.ease_factor, 2.5), coalesce(uw.repetition, 0), coalesce(uw.interval_days, 1)
from public.srs_cards c
join public.srs_notes n on n.id = c.note_id and n.provider = 'langfour'
join public.userwords uw on uw.user_id = n.user_id and uw.word_id = n.word_id
on conflict (card_id) do nothing;

insert into public.srs_reviews (card_id, reviewed_at, outcome)
select c.id, ft.tested_at at time zone 'utc', case when ft.test_result then 'good' else 'again' end
from public.flashcardtests ft
join public.srs_notes n on n.user_id = ft.user_id and n.word_id = ft.word_id and n.provider = 'langfour'
join public.srs_cards c on c.note_id = n.id
on conflict (card_id, reviewed_at) do nothing;

-- A last review the schedule records with no flashcardtests row near it (17
-- words on 2026-10-29): the known-words rule reads the latest review, so it
-- has to exist. A wrong answer set the interval to 0.
insert into public.srs_reviews (card_id, reviewed_at, outcome)
select c.id, uw.last_reviewed_at at time zone 'utc',
       case when uw.interval_days > 0 then 'good' else 'again' end
from public.userwords uw
join public.srs_notes n on n.user_id = uw.user_id and n.word_id = uw.word_id and n.provider = 'langfour'
join public.srs_cards c on c.note_id = n.id
where uw.last_reviewed_at is not null
  and not exists (select 1 from public.flashcardtests ft
                  where ft.user_id = uw.user_id and ft.word_id = uw.word_id
                    and abs(extract(epoch from ft.tested_at - uw.last_reviewed_at)) < 60)
on conflict (card_id, reviewed_at) do nothing;

-- ---------------------------------------------------------------------------
-- A review in Langfour: record it and reschedule the card with SM-2 (the
-- algorithm update_spaced_repetition always used). Returns the review's time,
-- or null when the user doesn't have the word. For the API, which passes the
-- user (practice.py); clients go through update_spaced_repetition.
-- ---------------------------------------------------------------------------
create or replace function public.srs_langfour_review(p_user_id uuid, p_word_id integer,
                                                      p_correct boolean)
returns timestamptz
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_card bigint;
    v_rep integer; v_interval integer; v_ease numeric;
    v_now timestamptz := now();
begin
    if not exists (select 1 from public.userwords
                   where user_id = p_user_id and word_id = p_word_id) then
        return null;
    end if;
    v_card := public.srs_langfour_card(p_user_id, p_word_id);
    select repetition, interval_days, ease_factor into v_rep, v_interval, v_ease
      from public.srs_card_sm2 where card_id = v_card for update;

    if p_correct then
        if v_rep = 0 then v_interval := 1;
        elsif v_rep = 1 then v_interval := 6;
        else v_interval := v_interval * v_ease;
        end if;
        v_rep := v_rep + 1;
        v_ease := v_ease + 0.15;
    else
        v_rep := 0;
        v_interval := 0;  -- due again right away
        v_ease := greatest(v_ease - 0.2, 1.3);
    end if;

    insert into public.srs_reviews (card_id, reviewed_at, outcome)
    values (v_card, v_now, case when p_correct then 'good' else 'again' end)
    on conflict (card_id, reviewed_at) do nothing;
    update public.srs_card_sm2
       set repetition = v_rep, interval_days = v_interval, ease_factor = v_ease
     where card_id = v_card;
    update public.srs_cards
       set next_due_at = v_now + make_interval(days => v_interval)
     where id = v_card;
    return v_now;
end;
$$;

revoke execute on function public.srs_langfour_review(uuid, integer, boolean) from public, anon, authenticated;
grant execute on function public.srs_langfour_review(uuid, integer, boolean) to service_role;

-- The web app's review session (updateFlashCardInfo.ts). It used to need a
-- second call, insert_flashcard_test, to record the answer; this records it.
create or replace function public.update_spaced_repetition(_word_id integer, _test_result boolean)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if (select auth.uid()) is null then
        raise exception 'Not signed in';
    end if;
    perform public.srs_langfour_review((select auth.uid()), _word_id, _test_result);
end;
$$;

revoke execute on function public.update_spaced_repetition(integer, boolean) from public, anon;
grant execute on function public.update_spaced_repetition(integer, boolean) to authenticated;

-- ---------------------------------------------------------------------------
-- Disconnecting an outside app hands reviews back to Langfour. Its due dates
-- carry over, so cards that went stale meanwhile don't all come due at once.
-- Called by the API (remnote_sync.revoke_token).
-- ---------------------------------------------------------------------------
create or replace function public.srs_carry_over_due(p_user_id uuid, p_provider text)
returns integer
language sql
security definer
set search_path = ''
as $$
    with due as (
        select n.word_id, min(c.next_due_at) as next_due_at
        from public.srs_notes n
        join public.srs_cards c on c.note_id = n.id
        where n.user_id = p_user_id and n.provider = p_provider
          and n.removed_at is null and c.next_due_at is not null
        group by n.word_id
    ),
    updated as (
        update public.srs_cards lc
           set next_due_at = due.next_due_at
          from public.srs_notes ln, due
         where ln.id = lc.note_id and ln.user_id = p_user_id and ln.provider = 'langfour'
           and ln.word_id = due.word_id
        returning 1
    )
    select count(*)::integer from updated;
$$;

revoke execute on function public.srs_carry_over_due(uuid, text) from public, anon, authenticated;
grant execute on function public.srs_carry_over_due(uuid, text) to service_role;

-- ---------------------------------------------------------------------------
-- The two list readers of Langfour's review session, now reading its cards.
-- Same signatures and output as before (the due date comes back as UTC
-- without a time zone, like the userwords column it replaces).
-- ---------------------------------------------------------------------------
create or replace function public.get_learning_words(order_direction text, cursor_word_id integer, search_term text, page_size integer, language_filter text, source_filter text)
returns table(word_id integer, word text, translation text, status text, review_due text, source text)
language plpgsql
set search_path to 'public', 'pg_temp'
as $function$
BEGIN
  RETURN QUERY
  WITH langfour_cards AS (
    SELECT n.word_id, c.id AS card_id, c.next_due_at AT TIME ZONE 'utc' AS next_review_due_at
    FROM srs_notes n
    JOIN srs_cards c ON c.note_id = n.id
    WHERE n.user_id = auth.uid() AND n.provider = 'langfour'
  ),
  flashcard_correct_tests AS (
    SELECT lc.word_id, COUNT(*) AS correct_count
    FROM langfour_cards lc
    JOIN srs_reviews r ON r.card_id = lc.card_id
    WHERE r.outcome <> 'again'
    GROUP BY lc.word_id
  ),
  user_words_with_status AS (
    SELECT
      uw.word_id,
      w.root                AS word,
      COALESCE(ut.custom_translation, w.translation) AS translation,
      (
        CASE
          WHEN uw.status = 'known' THEN 'known'
          WHEN uw.status = 'learning'
               AND COALESCE(fc.correct_count, 0) > 0
            THEN CAST(fc.correct_count AS text)
          WHEN uw.status = 'learning' THEN 'new'
          ELSE uw.status
        END
      )::text              AS status,
      lc.next_review_due_at,
      COALESCE(fc.correct_count, 0) AS correct_count,
      uw.source            AS source
    FROM UserWords uw
    JOIN words w
      ON uw.word_id = w.id
    LEFT JOIN UserTranslations ut
      ON uw.word_id = ut.word_id
      AND uw.user_id = ut.user_id
    LEFT JOIN langfour_cards lc
      ON uw.word_id = lc.word_id
    LEFT JOIN flashcard_correct_tests fc
      ON uw.word_id = fc.word_id
    WHERE uw.user_id = auth.uid()::uuid
      AND (language_filter IS NULL OR w.language = language_filter)
      AND (source_filter   IS NULL OR uw.source = source_filter)
      AND (
        (order_direction = 'DESC' AND uw.word_id < cursor_word_id)
        OR (order_direction <> 'DESC' AND uw.word_id > cursor_word_id)
        OR cursor_word_id = 0
      )
      AND (
        search_term IS NULL
        OR w.root ILIKE '%' || search_term || '%'
        OR COALESCE(ut.custom_translation, w.translation) ILIKE '%' || search_term || '%'
      )
  )
  SELECT
    uws.word_id,
    uws.word,
    uws.translation,
    uws.status,
    CASE
      WHEN uws.next_review_due_at::date = CURRENT_DATE THEN 'due today'
      WHEN uws.next_review_due_at IS NULL            THEN 'no review date'
      ELSE (uws.next_review_due_at::date - CURRENT_DATE)::text
    END AS review_due,
    uws.source
  FROM user_words_with_status uws
  WHERE uws.status NOT IN ('known', 'disabled')
  ORDER BY
    (uws.status <> 'new') DESC,
    CASE WHEN order_direction = 'DESC' THEN uws.word_id END DESC,
    CASE WHEN order_direction = 'ASC'  OR order_direction IS NULL THEN uws.word_id END ASC
  FETCH NEXT page_size ROWS ONLY;
END;
$function$;

create or replace function public.get_userwords_filtered(language_filter text, due_type text, page_size integer, p_source text default null::text)
returns table(word_id integer, word_root text, translation text, next_review_due_at timestamp without time zone)
language plpgsql
set search_path to 'public', 'pg_temp'
as $function$
BEGIN
    RETURN QUERY
    SELECT
        uw.word_id,
        w.root AS word_root,
        COALESCE(ut.custom_translation, w.translation) AS translation,
        c.next_due_at AT TIME ZONE 'utc'
    FROM userwords            AS uw
    JOIN words                AS w  ON uw.word_id = w.id
    JOIN srs_notes            AS n  ON n.user_id = uw.user_id AND n.word_id = uw.word_id
                                   AND n.provider = 'langfour'
    JOIN srs_cards            AS c  ON c.note_id = n.id
    LEFT JOIN usertranslations ut
           ON ut.word_id = w.id
          AND ut.user_id = auth.uid()
    WHERE uw.user_id = auth.uid()
      AND uw.status <> 'disabled'
      AND w.language = language_filter
      AND (p_source IS NULL OR uw.source = p_source)     -- ← only filters if supplied
      AND (
            (due_type = 'today'   AND (c.next_due_at AT TIME ZONE 'utc')::date = CURRENT_DATE) OR
            (due_type = 'overdue' AND (c.next_due_at AT TIME ZONE 'utc') <  CURRENT_DATE)      OR
            (due_type = 'both'    AND ((c.next_due_at AT TIME ZONE 'utc') < CURRENT_DATE
                                    OR  (c.next_due_at AT TIME ZONE 'utc')::date = CURRENT_DATE))
          )
    ORDER BY c.next_due_at
    FETCH NEXT page_size ROWS ONLY;
END;
$function$;
