-- word_events: what a user did with a word outside any flashcard system.
--
-- Reviews live in the review tables (srs_reviews, flashcardtests). This log
-- holds the rest: saving a word (with where it was met), looking it up,
-- reading or hearing it, and recalling it in a ChatGPT practice session (MCP
-- server). Future scoring reads reviews plus these events; nothing derives a
-- stored "known" from them (user_known_words stays computed).
--
-- Append-only. Scoring must be able to recompute from history and get the
-- same answer, so clients may insert and read their own rows but never update
-- or delete them. Delivery state for recalls that go on to a flashcard lives
-- in srs_outbox (srs_outbox.sql), not here. The one sanctioned update is
-- merge_roots moving a merged root's events to the surviving root, which is a
-- dictionary correction run with the service role.
--
-- Replaces userwordinteraction: the same idea (word, location, seen_at), never
-- written to, read only by get_user_counts_with_wordforms for a "seen" count
-- that was always 0.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other files
-- here. Idempotent.

create table if not exists public.word_events (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users (id) on delete cascade,
    word_id     integer not null references public.words (id),
    kind        text not null check (kind in
                    ('saved', 'lookup', 'exposure', 'recall_correct', 'recall_wrong')),
    source      text not null check (source in
                    ('chatgpt', 'reader', 'video', 'extension', 'web')),
    occurred_at timestamptz not null default now(),
    -- Where it happened, for 'saved' in particular:
    -- {"site", "title", "episode", "sentence"}. Free-form; nothing filters on it.
    context     jsonb
);

create index if not exists word_events_user_word on public.word_events (user_id, word_id);
create index if not exists word_events_user_time on public.word_events (user_id, occurred_at);

alter table public.word_events enable row level security;

drop policy if exists word_events_select_own on public.word_events;
create policy word_events_select_own on public.word_events
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists word_events_insert_own on public.word_events;
create policy word_events_insert_own on public.word_events
    for insert to authenticated
    with check (user_id = (select auth.uid()));

-- No update or delete policy, and no grant either: append-only for clients.
revoke update, delete, truncate on public.word_events from anon, authenticated;

-- Several events in one call, for the signed-in user. rows is a JSON array of
-- {word_id, kind, source, occurred_at?, context?}; occurred_at defaults to now.
-- Security invoker, so RLS checks every row.
create or replace function public.record_word_events(rows jsonb)
returns integer
language sql
security invoker
set search_path = ''
as $$
    with inserted as (
        insert into public.word_events (user_id, word_id, kind, source, occurred_at, context)
        select (select auth.uid()), r.word_id, r.kind, r.source,
               coalesce(r.occurred_at, now()), r.context
        from jsonb_to_recordset(rows)
             as r(word_id integer, kind text, source text, occurred_at timestamptz, context jsonb)
        returning 1
    )
    select count(*)::integer from inserted;
$$;

revoke execute on function public.record_word_events(jsonb) from public, anon;
grant execute on function public.record_word_events(jsonb) to authenticated, service_role;

-- The word popup's counts. seencount reads exposures from word_events, and
-- reviewcount the reviews of the word's live notes in Langfour and any
-- connected app (as word_progress does). It used to count only flashcardtests,
-- so a RemNote user always saw 0 reviews; since langfour_provider.sql moved
-- Langfour's reviews into srs_reviews, that one table holds them all.
create or replace function public.get_user_counts_with_wordforms(_word_id integer)
returns table (reviewcount integer, seencount integer, alternative_wordforms text[])
language sql
stable
set search_path = ''
as $$
    select
        (select count(*)::integer
             from public.srs_reviews r
             join public.srs_cards c on c.id = r.card_id
             join public.srs_notes n on n.id = c.note_id
            where n.user_id = (select auth.uid()) and n.word_id = _word_id
              and n.removed_at is null),
        (select count(*)::integer from public.word_events e
          where e.user_id = (select auth.uid()) and e.word_id = _word_id
            and e.kind = 'exposure'),
        coalesce((select array_agg(distinct wf.form) from public.wordforms wf
                   where wf.word_id = _word_id), array[]::text[]);
$$;

drop table if exists public.userwordinteraction;
