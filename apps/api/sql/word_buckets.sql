-- word buckets: the Media and video word list as three groups, for accounts
-- that have them on (word_familiarity.py).
--
--   userdata.known_languages    the other languages a learner reads, as cognate
--                               sources. Null keeps the old list; set per account.
--   user_word_familiarity       Jev's rating of whether this learner can work a
--                               word out from what they know, saved per user and
--                               word because it hardly depends on the text.
--   userwords.familiar_until    a word added as "probably know" stays out of
--                               RemNote and out of practice until this date.
--   add_bucket_words            saves the words of the first two groups.
--
-- "Half-way to known": a word is known once a correct review leaves a gap of 21+
-- days (known_words.sql). A probably-know word starts at repetition 2 with half
-- that interval, so its first correct review (11 * 2.5 = 27 days) makes it known
-- and a wrong one sends it back to the start. It has no review yet, so it doesn't
-- count as known before that. Due dates spread over 8-14 days, so words added
-- together don't all come due at once.
--
-- RemNote can't take a due date or an interval, only a score, so there the card
-- is created after familiar_until and RemNote schedules it as a new card.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other files
-- here. Idempotent. mcp_vocabulary.sql has the matching filter on familiar_until.

alter table public.userdata
    add column if not exists known_languages text[];

alter table public.userwords
    add column if not exists familiar_until timestamptz;

create table if not exists public.user_word_familiarity (
    user_id         uuid not null references auth.users (id) on delete cascade,
    word_id         integer not null references public.words (id) on delete cascade,
    score           numeric(3, 2) not null,
    rubric_version  smallint not null,
    rated_at        timestamptz not null default now(),
    primary key (user_id, word_id)
);

alter table public.user_word_familiarity enable row level security;
-- Only the API's service role reads or writes it, like video_word_ranks.
revoke all on public.user_word_familiarity from anon, authenticated;

-- What the learner changed in the list, so we can see how often Jev is wrong.
alter table public.word_events drop constraint if exists word_events_kind_check;
alter table public.word_events add constraint word_events_kind_check check (kind in
    ('saved', 'lookup', 'exposure', 'recall_correct', 'recall_wrong', 'bucket_move'));

create or replace function public.add_bucket_words(p_user_id uuid, p_familiar integer[],
                                                   p_priority integer[], p_source text)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_familiar integer[];
    v_priority integer;
begin
    -- Words already on the list keep their status and schedule. The trigger on
    -- userwords (langfour_provider.sql) makes the card, due on next_review_due_at.
    with added as (
        insert into public.userwords (user_id, word_id, status, source, next_review_due_at,
                                      repetition, interval_days, familiar_until)
        select p_user_id, f.word_id, 'learning', p_source,
               (now() + make_interval(days => 8 + f.word_id % 7)) at time zone 'utc',
               2, 11, now() + make_interval(days => 8 + f.word_id % 7)
        from (select distinct unnest(p_familiar) as word_id) f
        on conflict (user_id, word_id) do nothing
        returning word_id
    )
    select coalesce(array_agg(word_id), '{}') into v_familiar from added;

    update public.srs_card_sm2 s
       set repetition = 2, interval_days = 11
      from public.srs_cards c
      join public.srs_notes n on n.id = c.note_id
     where s.card_id = c.id
       and n.user_id = p_user_id and n.provider = 'langfour'
       and n.word_id = any(v_familiar);

    with added as (
        insert into public.userwords (user_id, word_id, status, source)
        select p_user_id, p.word_id, 'learning', p_source
        from (select distinct unnest(p_priority) as word_id) p
        on conflict (user_id, word_id) do nothing
        returning word_id
    )
    select count(*) into v_priority from added;

    if cardinality(v_familiar) + v_priority > 0 then
        update public.userdata set known_words_updated_at = current_timestamp
         where user_id = p_user_id;
    end if;
    return cardinality(v_familiar) + v_priority;
end;
$$;

revoke execute on function public.add_bucket_words(uuid, integer[], integer[], text)
    from public, anon, authenticated;
grant execute on function public.add_bucket_words(uuid, integer[], integer[], text) to service_role;
