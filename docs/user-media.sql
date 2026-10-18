-- user_media: each user's Library (episodes, movies, articles, songs).
--
-- Runbook, applied by hand through the Supabase connector as migration
-- `user_media` on project Lang; there is no CLI setup that runs this file.
-- Kept here so the schema can be reviewed with the code that uses it
-- (apps/api/media_import.py).
--
-- The API writes with the service-role key (bypasses RLS) because an import
-- has to be parsed server-side, and filters every query on user_id itself.
-- RLS is the second line: signed-in clients can read and delete only their
-- own rows, and cannot insert or edit them; anon gets nothing.

create table if not exists public.user_media (
    user_id             uuid not null references auth.users (id) on delete cascade,
    language            text not null check (language in ('es', 'de', 'it', 'fr')),
    id                  text not null check (id ~ '^[a-zA-Z0-9_-]+$'),
    kind                text not null check (kind in ('series', 'movie', 'article', 'song', 'text')),
    title               text not null,
    series              text,
    season              integer check (season >= 0),
    episode             integer check (episode >= 0),
    artist              text,
    site                text,
    source_url          text,
    duration            double precision,
    word_count          integer not null default 0,
    transcription_model text,
    timebase            text,
    -- [{timestamp: [start, end] | null, text}], the text as imported.
    chunks              jsonb not null,
    -- Parsed words, the shape the videos' *_processed.json "content" has.
    words               jsonb not null default '[]'::jsonb,
    imported_at         timestamptz not null default now(),
    primary key (user_id, language, id)
);

alter table public.user_media enable row level security;

drop policy if exists user_media_select_own on public.user_media;
create policy user_media_select_own on public.user_media
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists user_media_delete_own on public.user_media;
create policy user_media_delete_own on public.user_media
    for delete to authenticated
    using (user_id = (select auth.uid()));

revoke all on public.user_media from anon;
revoke insert, update on public.user_media from authenticated;
