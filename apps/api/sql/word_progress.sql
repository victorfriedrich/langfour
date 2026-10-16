-- The signed-in user's progress with one word, for the reader's word sheet.
--
-- status          as in classify_words: known, learning, ignored or new
-- added_at        when the word went into the user's words
-- review_count    reviews in both systems: Langfour's own (flashcardtests)
--                 and RemNote's (srs_reviews), like user_known_words counts
--                 both; get_user_counts_with_wordforms only sees Langfour's
-- correct_count   of those, answered right (RemNote: anything but 'again')
-- last_reviewed_at
-- next_review_at  from whichever system schedules the user now
--                 (userdata.review_provider): Langfour's SM-2 due date, or
--                 the earliest due card of the word's RemNote note
--
-- userwords and flashcardtests store UTC without a time zone; they are
-- returned as timestamptz so the client can show local dates.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other
-- files here. Idempotent.

create or replace function public.word_progress(word_id_param integer)
returns table (
    status text,
    added_at timestamptz,
    review_count integer,
    correct_count integer,
    last_reviewed_at timestamptz,
    next_review_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
    with me as (
        select (select auth.uid()) as user_id
    ),
    mine as (
        select uw.*
        from public.userwords uw, me
        where uw.user_id = me.user_id and uw.word_id = word_id_param
    ),
    remnote_cards as (
        select c.id, c.next_due_at
        from public.srs_cards c
        join public.srs_notes n on n.id = c.note_id, me
        where n.user_id = me.user_id
          and n.word_id = word_id_param
          and n.removed_at is null
    ),
    reviews as (
        select ft.tested_at at time zone 'utc' as reviewed_at, ft.test_result as correct
        from public.flashcardtests ft, me
        where ft.user_id = me.user_id and ft.word_id = word_id_param
        union all
        select r.reviewed_at, r.outcome <> 'again'
        from public.srs_reviews r
        join remnote_cards c on c.id = r.card_id
    ),
    provider as (
        select coalesce(
            (select d.review_provider from public.userdata d, me where d.user_id = me.user_id),
            'langfour'
        ) as name
    )
    select
        case
            when exists (
                select 1 from public.user_known_words k, me
                where k.user_id = me.user_id and k.word_id = word_id_param
            ) then 'known'
            when (select m.status from mine m) = 'disabled' then 'ignored'
            when exists (select 1 from mine) then 'learning'
            else 'new'
        end,
        (select m.created_at at time zone 'utc' from mine m),
        (select count(*)::integer from reviews),
        (select count(*) filter (where correct)::integer from reviews),
        greatest(
            (select max(r.reviewed_at) from reviews r),
            (select m.last_reviewed_at at time zone 'utc' from mine m)
        ),
        case
            when (select name from provider) = 'remnote' then (select min(c.next_due_at) from remnote_cards c)
            else (select m.next_review_due_at at time zone 'utc' from mine m)
        end;
$$;

grant execute on function public.word_progress(integer) to authenticated;
