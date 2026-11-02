-- watch_events: which videos a user watched, and how much of each.
--
-- One row per user and video. Two sources write it, both through the API
-- with the service role:
--
--   desktop  the extension counted 70% of the video played on youtube.com
--   history  the extension read youtube.com/feed/history with the user's own
--            sign-in, after their consent; the red progress bar gives `share`
--
-- A row is "watched" when it isn't unmarked and 70% was played or the share
-- is unknown. A history row under 70% is a video the user started and left:
-- kept, so a later read can see the bar grow, but not watched. Unmark sets
-- unmarked_at rather than deleting, so the next history read doesn't bring
-- the video straight back; watching it again on desktop, or, for a row the
-- history page marked, its bar growing past 70%, marks it again. The rules
-- live in apps/api/watch.py.
--
--   watched_at   when it was watched; null for history rows from before the
--                first read, whose day the history page doesn't say
--   share        0..1 of the video played, when known
--
-- This replaces videos_seen. Its 383 rows came mostly from the Videos page's
-- "Hide & mark as seen" button, used to dismiss videos rather than to say
-- they were watched, so they don't move across: the table goes to the
-- archive schema, and its two functions (get_seen_video_ids,
-- mark_video_as_seen) are dropped, their definitions kept in
-- archive.dropped_functions. The recommender reads watch_events instead.
--
-- Also userdata.watch_recap_closed_on: the day whose recap ("Yesterday on
-- YouTube") the user put away with "Not now", so it stays away on the web and
-- in the extension.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other files
-- here, in one transaction. Not idempotent: run it once. Applied 2026-11-02
-- as migration watch_events.

begin;

-- 1. The table.
create table public.watch_events (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users (id) on delete cascade,
    video_id    text not null check (video_id ~ '^[A-Za-z0-9_-]{11}$'),
    language    text not null check (language in ('es', 'de', 'it', 'fr')),
    watched_at  timestamptz,
    share       real check (share between 0 and 1),
    source      text not null check (source in ('desktop', 'history')),
    unmarked_at timestamptz,
    created_at  timestamptz not null default now(),
    unique (user_id, video_id)
);

create index watch_events_user_time on public.watch_events (user_id, watched_at);

-- Own rows only, like user_media: users read and delete theirs, and only the
-- API writes.
alter table public.watch_events enable row level security;
create policy watch_events_select_own on public.watch_events
    for select to authenticated using (user_id = (select auth.uid()));
create policy watch_events_delete_own on public.watch_events
    for delete to authenticated using (user_id = (select auth.uid()));
revoke all on public.watch_events from anon;
revoke insert, update, truncate on public.watch_events from authenticated;

-- 2. videos_seen out of the way, kept in the archive.
insert into archive.dropped_functions (signature, definition)
select p.oid::regprocedure::text, pg_get_functiondef(p.oid)
from pg_proc p
where p.oid in ('public.get_seen_video_ids()'::regprocedure,
                'public.mark_video_as_seen(text)'::regprocedure);

drop function public.get_seen_video_ids();
drop function public.mark_video_as_seen(text);

alter table public.videos_seen set schema archive;
alter table archive.videos_seen rename to videos_seen_2026_11;
revoke all on archive.videos_seen_2026_11 from anon, authenticated;

-- 3. "Not now" on the recap.
alter table public.userdata add column if not exists watch_recap_closed_on date;

commit;
