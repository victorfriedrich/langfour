-- video_queue: the seam between discovery/selection and ingestion.
--
-- Before: `ytpipeline export` wrote a JSON worklist and videoscraper.py mutated
-- the same file to record progress, so every re-export silently reset every
-- `processed` marker. A file cannot be a queue with two writers.
--
-- After: one row per video. `ytpipeline select` upserts with
-- ignore_duplicates, so a row that already exists -- and its status -- is never
-- touched. ingest.py claims rows with a compare-and-set on status, so several
-- workers can drain the same queue. Anything may insert a row (discovery, a
-- person, an API endpoint acting for a signed-in user); ingestion does not care
-- where a video came from. Transcript bodies stay on disk / in object storage;
-- this table holds metadata and state only.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, exactly like
-- docs/language-iso-migration.sql. The deployed database is the source of
-- truth; this file is the runbook and the review artifact. Idempotent: safe to
-- re-run.

create table if not exists public.video_queue (
    video_id     text primary key,
    -- ISO 639-1, matching languages.py and words.language.
    lang         text not null check (lang in ('es', 'de', 'it', 'fr')),
    channel_id   text,
    title        text,
    duration_s   integer,
    views        bigint,
    score        real not null default 0,      -- selection rank within its channel
    source       text not null default 'discovery'
                 check (source in ('discovery', 'user', 'manual', 'legacy')),
    priority     smallint not null default 0,  -- discovery 0 < user 10 < manual 20
    status       text not null default 'pending'
                 check (status in ('pending', 'processing', 'done', 'failed', 'skipped')),
    attempts     smallint not null default 0,
    error        text,
    submitted_by uuid references auth.users (id) on delete set null,
    created_at   timestamptz not null default now(),
    claimed_at   timestamptz,
    done_at      timestamptz
);

-- score is NOT NULL because Postgres sorts NULLs FIRST under `order by score
-- desc`: while it was nullable, every unscored submission silently preempted
-- every scored discovery row. Ranking between sources belongs to `priority`.

-- The only hot query: next pending rows for a language.
create index if not exists video_queue_pending
    on public.video_queue (lang, priority desc, score desc)
    where status = 'pending';
create index if not exists video_queue_channel on public.video_queue (channel_id);

-- The API and both pipeline scripts run as service_role, which bypasses RLS.
-- These policies exist solely for a client submitting on a user's behalf.
alter table public.video_queue enable row level security;

drop policy if exists "users read own submissions" on public.video_queue;
create policy "users read own submissions" on public.video_queue
    for select to authenticated
    using (submitted_by = auth.uid());

drop policy if exists "users queue own videos" on public.video_queue;
create policy "users queue own videos" on public.video_queue
    for insert to authenticated
    -- priority pinned to the exact value for a user submission: it outranks
    -- discovery deliberately, and a client cannot award itself more than that.
    with check (submitted_by = auth.uid()
                and source = 'user' and status = 'pending' and priority = 10);
