-- video_hides: what a learner chose not to see on the Videos page
-- (docs/plans/home-redesign.md, screen 3; home.py).
--
-- Not interested on a card hides that video; "Hide all from <channel>" in the
-- pill that follows hides the channel. Undo deletes the row. The home grid
-- leaves both out; nothing else about the recommendations changes, so the
-- page doesn't claim "you'll see fewer videos like it".
--
--   kind   video | channel
--   key    the YouTube video id, or the channel's name as the transcripts
--          store it ("creator"): the one channel identity the recommender
--          has for every video
--
-- The API reads and writes these with the service role on the signed-in
-- user's behalf. The policies below let a client read and change its own
-- rows and nothing else, like channel_favourites.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent. Until it is applied the Videos page hides
-- nothing (home.py reads a missing table as no rows).

create table if not exists public.video_hides (
    user_id    uuid not null references auth.users (id) on delete cascade,
    language   text not null check (language in ('es', 'de', 'it', 'fr')),
    kind       text not null check (kind in ('video', 'channel')),
    key        text not null check (char_length(key) between 1 and 200),
    created_at timestamptz not null default now(),
    primary key (user_id, language, kind, key)
);

alter table public.video_hides enable row level security;

drop policy if exists video_hides_select_own on public.video_hides;
create policy video_hides_select_own on public.video_hides
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists video_hides_insert_own on public.video_hides;
create policy video_hides_insert_own on public.video_hides
    for insert to authenticated
    with check (user_id = (select auth.uid()));

drop policy if exists video_hides_delete_own on public.video_hides;
create policy video_hides_delete_own on public.video_hides
    for delete to authenticated
    using (user_id = (select auth.uid()));

revoke update, truncate on public.video_hides from anon, authenticated;
