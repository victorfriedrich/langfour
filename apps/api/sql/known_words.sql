-- Known words: one definition for the whole product.
--
-- A word is known to Langfour when the user said so (userwords.status =
-- 'known': onboarding, imports, "I already know these"), or when their reviews
-- show it has stuck. userwords.status records only the decision; whether
-- reviews have proven a word is computed here, so it can never go stale and
-- a forgotten word drops out on its own.
--
-- "Learned in reviews" mirrors the plugin's stats module
-- (apps/remnote-plugin/src/stats.ts), which draws the progress views: last
-- answer correct, a gap of 21+ days before the next review, and not more
-- than half that gap overdue. Keep the two in step (LEARNED_DAYS = 21,
-- OVERDUE_GRACE = 0.5).
--
-- Both review systems count, whichever one schedules the user now: a word
-- learned in Langfour before they switched to RemNote stays known until it
-- falls overdue.
--
-- Readers: the recommender (video ranking, word suggestions, coverage) and
-- the Vocabulary page. HOW THIS GETS APPLIED: through the Supabase connector,
-- like the other files here. Idempotent.

create or replace view public.user_known_words
with (security_invoker = true)  -- a signed-in user sees only their own rows (RLS)
as
select distinct on (user_id, word_id) user_id, word_id, source
from (
    -- Declared known.
    select uw.user_id, uw.word_id, 'declared' as source, 1 as priority
    from public.userwords uw
    where uw.status = 'known'

    union all

    -- Learned in Langfour's own reviews. update_spaced_repetition keeps the
    -- current gap in interval_days and sets it to 0 on a wrong answer.
    select uw.user_id, uw.word_id, 'reviews', 2
    from public.userwords uw
    where uw.status = 'learning'
      and uw.interval_days >= 21
      and uw.last_reviewed_at is not null
      and now() <= uw.next_review_due_at + make_interval(days => uw.interval_days) * 0.5

    union all

    -- Learned in RemNote: every card of the note, judged by its latest review.
    select n.user_id, n.word_id, 'reviews', 2
    from public.srs_notes n
    where n.removed_at is null
      and exists (select 1 from public.srs_cards c where c.note_id = n.id)
      and not exists (
          select 1
          from public.srs_cards c
          left join lateral (
              select r.reviewed_at, r.outcome
              from public.srs_reviews r
              where r.card_id = c.id
              order by r.reviewed_at desc
              limit 1
          ) last on true
          where c.note_id = n.id
            and not (
                last.reviewed_at is not null
                and last.outcome <> 'again'
                and c.next_due_at is not null
                and c.next_due_at - last.reviewed_at >= interval '21 days'
                and now() <= c.next_due_at + (c.next_due_at - last.reviewed_at) * 0.5
            )
      )
) known
order by user_id, word_id, priority;

-- Counts for the Vocabulary page, in the signed-in user's language.
create or replace function public.known_words_summary(language_filter text)
returns table (declared integer, from_reviews integer)
language sql
stable
security invoker
set search_path = ''
as $$
    select count(*) filter (where k.source = 'declared')::integer,
           count(*) filter (where k.source = 'reviews')::integer
    from public.user_known_words k
    join public.words w on w.id = k.word_id
    where k.user_id = (select auth.uid())
      and w.language = language_filter;
$$;

grant select on public.user_known_words to authenticated, service_role;
grant execute on function public.known_words_summary(text) to authenticated;

-- The Vocabulary list: known words in a language, a page at a time.
create or replace function public.get_known_words_page(
    language_filter text,
    search_term text default null,
    cursor_word_id integer default 0,
    page_size integer default 50
)
returns table (word_id integer, word text, translation text, source text)
language sql
stable
security invoker
set search_path = ''
as $$
    select k.word_id, w.root, coalesce(ut.custom_translation, w.translation), k.source
    from public.user_known_words k
    join public.words w on w.id = k.word_id
    left join lateral (
        select t.custom_translation from public.usertranslations t
        where t.user_id = k.user_id and t.word_id = k.word_id
        order by t.created_at desc limit 1
    ) ut on true
    where k.user_id = (select auth.uid())
      and w.language = language_filter
      and k.word_id > cursor_word_id
      and (search_term is null
           or w.root ilike '%' || search_term || '%'
           or coalesce(ut.custom_translation, w.translation) ilike '%' || search_term || '%')
    order by k.word_id
    limit page_size;
$$;

grant execute on function public.get_known_words_page(text, text, integer, integer) to authenticated;
