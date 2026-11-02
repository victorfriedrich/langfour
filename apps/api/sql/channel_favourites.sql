-- channel_favourites: the channels a learner marked Favourite on YouTube
-- (docs/plans/youtube-plan.md, feature 4; channels.py).
--
-- A plain toggle: a row means "favourite", deleting it unfavourites. lang is
-- the learner's language when they favourited, which is the language the
-- channel's videos were queued in.
--
-- The API reads and writes these with the service role on the signed-in
-- user's behalf. The policies below let a client read and change its own
-- rows and nothing else, like user_media.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent.

create table if not exists public.channel_favourites (
    user_id    uuid not null references auth.users (id) on delete cascade,
    -- The canonical UC... id, never a @handle: handles change, and
    -- video_queue.channel_id holds the UC id.
    channel_id text not null check (channel_id ~ '^UC[A-Za-z0-9_-]{22}$'),
    lang       text not null check (lang in ('es', 'de', 'it', 'fr')),
    created_at timestamptz not null default now(),
    -- How listing its uploads went (channels.queue_channel). Null until one
    -- finishes: no YouTube key, no worker for the language, a limit, or a
    -- failure all leave it null, and the next visit to the channel tries again.
    uploads_outcome text check (uploads_outcome in ('queued', 'other_language')),
    primary key (user_id, channel_id)
);

alter table public.channel_favourites add column if not exists uploads_outcome text
    check (uploads_outcome in ('queued', 'other_language'));

-- "Learners at your level also love" will count favourites per channel.
create index if not exists channel_favourites_channel on public.channel_favourites (channel_id);

alter table public.channel_favourites enable row level security;

drop policy if exists channel_favourites_select_own on public.channel_favourites;
create policy channel_favourites_select_own on public.channel_favourites
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists channel_favourites_insert_own on public.channel_favourites;
create policy channel_favourites_insert_own on public.channel_favourites
    for insert to authenticated
    with check (user_id = (select auth.uid()));

drop policy if exists channel_favourites_delete_own on public.channel_favourites;
create policy channel_favourites_delete_own on public.channel_favourites
    for delete to authenticated
    using (user_id = (select auth.uid()));

revoke update, truncate on public.channel_favourites from anon, authenticated;
