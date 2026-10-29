-- The signed-in user's progress with one word, for the reader's word sheet.
--
-- status          as in classify_words: known, learning, ignored or new
-- added_at        when the word went into the user's words
-- review_count    reviews of the word's live notes, in Langfour and any
--                 connected app (srs_reviews), like user_known_words counts
--                 them
-- correct_count   of those, answered right (anything but 'again')
-- last_reviewed_at
-- next_review_at  from whichever scheduler the user has now
--                 (userdata.review_provider): the earliest due card of the
--                 word's note there
--
-- userwords stores UTC without a time zone; added_at is returned as
-- timestamptz so the client can show local dates.
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
    cards as (
        select c.id, c.next_due_at, n.provider
        from public.srs_cards c
        join public.srs_notes n on n.id = c.note_id, me
        where n.user_id = me.user_id
          and n.word_id = word_id_param
          and n.removed_at is null
    ),
    reviews as (
        select r.reviewed_at, r.outcome <> 'again' as correct
        from public.srs_reviews r
        join cards c on c.id = r.card_id
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
        (select max(r.reviewed_at) from reviews r),
        (select min(c.next_due_at) from cards c where c.provider = (select name from provider));
$$;

grant execute on function public.word_progress(integer) to authenticated;
