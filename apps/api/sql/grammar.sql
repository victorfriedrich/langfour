-- Grammar progress for the MCP grammar tools (grammar.py, mcp_server.py;
-- design in docs/plans/grammar-tracking.md).
--
-- The curriculum itself (chapters and concepts) is not in the database: the
-- API reads it from apps/api/grammar/<language>/*.yaml, so concept_id and
-- chapter_id here are the stable slugs from those files ('es.ser_estar_1',
-- 'es.ser_estar_1.characteristic_vs_state'). A concept removed from the files
-- leaves its rows behind, and the API ignores them.
--
--   user_grammar_chapters  how far the user is in the book: started or done
--                          (no row = not started)
--   user_grammar_concepts  when each concept was last practised and when it
--                          should be worked back in (refresh_at)
--   grammar_events         what the AI app reported, append-only, like
--                          word_events
--
-- The refresh rule lives in grammar.py. record_grammar only writes what the
-- API computed, so the events and the new state land in one transaction.
--
-- The API calls everything with the service role on behalf of an OAuth user
-- (docs/mcp-oauth.md), so clients only read their own rows and never write.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other files
-- here. Idempotent.

create table if not exists public.user_grammar_chapters (
    user_id     uuid not null references auth.users (id) on delete cascade,
    chapter_id  text not null,
    status      text not null check (status in ('started', 'done')),
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    primary key (user_id, chapter_id)
);

create table if not exists public.user_grammar_concepts (
    user_id           uuid not null references auth.users (id) on delete cascade,
    concept_id        text not null,
    first_correct_at  timestamptz,           -- null until practised correctly
    last_seen_at      timestamptz,
    last_produced_at  timestamptz,
    interval_days     integer check (interval_days between 1 and 180),
    interval_grown_at timestamptz,
    refresh_at        timestamptz,           -- fading once this has passed
    produced_count    integer not null default 0,
    error_count       integer not null default 0,
    primary key (user_id, concept_id)
);

create table if not exists public.grammar_events (
    id            bigint generated always as identity primary key,
    user_id       uuid not null references auth.users (id) on delete cascade,
    concept_id    text not null,
    kind          text not null check (kind in ('seen', 'produced')),
    correct       boolean,                   -- set for 'produced' only
    self_reported boolean not null default false,
    sentence      text check (char_length(sentence) <= 300),
    source        text not null check (source in ('chatgpt', 'reader', 'web')),
    occurred_at   timestamptz not null default now(),
    check ((kind = 'produced') = (correct is not null))
);

create index if not exists grammar_events_user_time on public.grammar_events (user_id, occurred_at);

alter table public.user_grammar_chapters enable row level security;
alter table public.user_grammar_concepts enable row level security;
alter table public.grammar_events enable row level security;

drop policy if exists user_grammar_chapters_select_own on public.user_grammar_chapters;
create policy user_grammar_chapters_select_own on public.user_grammar_chapters
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists user_grammar_concepts_select_own on public.user_grammar_concepts;
create policy user_grammar_concepts_select_own on public.user_grammar_concepts
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists grammar_events_select_own on public.grammar_events;
create policy grammar_events_select_own on public.grammar_events
    for select to authenticated
    using (user_id = (select auth.uid()));

-- Written only by the API.
revoke insert, update, delete, truncate on public.user_grammar_chapters from anon, authenticated;
revoke insert, update, delete, truncate on public.user_grammar_concepts from anon, authenticated;
revoke insert, update, delete, truncate on public.grammar_events from anon, authenticated;

-- One session's report, in one transaction. Every argument is a JSON array of
-- rows the API already computed:
--   p_events    [{concept_id, kind, correct, self_reported, sentence}]
--   p_concepts  full user_grammar_concepts rows, minus user_id
--   p_chapters  full user_grammar_chapters rows, minus user_id
-- Returns the number of events inserted.
create or replace function public.record_grammar(p_user_id uuid, p_events jsonb,
                                                 p_concepts jsonb, p_chapters jsonb)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_inserted integer;
begin
    insert into public.user_grammar_chapters (user_id, chapter_id, status, started_at, finished_at)
    select p_user_id, r.chapter_id, r.status, r.started_at, r.finished_at
    from jsonb_to_recordset(p_chapters)
         as r(chapter_id text, status text, started_at timestamptz, finished_at timestamptz)
    on conflict (user_id, chapter_id) do update
        set status = excluded.status,
            started_at = excluded.started_at,
            finished_at = excluded.finished_at;

    insert into public.user_grammar_concepts (
        user_id, concept_id, first_correct_at, last_seen_at, last_produced_at,
        interval_days, interval_grown_at, refresh_at, produced_count, error_count)
    select p_user_id, r.concept_id, r.first_correct_at, r.last_seen_at, r.last_produced_at,
           r.interval_days, r.interval_grown_at, r.refresh_at, r.produced_count, r.error_count
    from jsonb_to_recordset(p_concepts)
         as r(concept_id text, first_correct_at timestamptz, last_seen_at timestamptz,
              last_produced_at timestamptz, interval_days integer,
              interval_grown_at timestamptz, refresh_at timestamptz,
              produced_count integer, error_count integer)
    on conflict (user_id, concept_id) do update
        set first_correct_at = excluded.first_correct_at,
            last_seen_at = excluded.last_seen_at,
            last_produced_at = excluded.last_produced_at,
            interval_days = excluded.interval_days,
            interval_grown_at = excluded.interval_grown_at,
            refresh_at = excluded.refresh_at,
            produced_count = excluded.produced_count,
            error_count = excluded.error_count;

    insert into public.grammar_events (user_id, concept_id, kind, correct, self_reported,
                                       sentence, source)
    select p_user_id, r.concept_id, r.kind, r.correct, coalesce(r.self_reported, false),
           r.sentence, 'chatgpt'
    from jsonb_to_recordset(p_events)
         as r(concept_id text, kind text, correct boolean, self_reported boolean, sentence text);
    get diagnostics v_inserted = row_count;

    return v_inserted;
end;
$$;

revoke execute on function public.record_grammar(uuid, jsonb, jsonb, jsonb)
    from public, anon, authenticated;
grant execute on function public.record_grammar(uuid, jsonb, jsonb, jsonb) to service_role;
