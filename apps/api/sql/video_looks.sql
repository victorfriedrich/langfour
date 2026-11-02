-- video_looks: a vision model's verdict on each video's thumbnail and title
-- (video_looks.py), for the recommendation order (video_blend.py).
--
-- One row per video, written by scripts/judge_thumbnails.py. Only videos in the
-- top 20% by known words for the accounts that script is given get a row; the
-- rest count as average. The recommender reads this at startup, and a language
-- with no rows keeps its plain known-words order.
--
--   interest   would a curious adult enjoy watching this, 1..10
--   trash      how cheap or clickbait-y it looks, 1..10
--   polish     production quality of the thumbnail, 1..10 (not used yet)
--   sensitive  none | mild | strong
--   genre      video_looks.GENRES (not used yet)
--   channel    the video's creator, for the per-channel limit
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent. Only the API's service role reads or writes it.

create table if not exists public.video_looks (
    video_id   text primary key,
    language   text not null check (language in ('es', 'de', 'it', 'fr')),
    channel    text,
    interest   smallint not null check (interest between 1 and 10),
    trash      smallint not null check (trash between 1 and 10),
    polish     smallint not null check (polish between 1 and 10),
    sensitive  text not null check (sensitive in ('none', 'mild', 'strong')),
    genre      text not null,
    model      text not null,
    judged_at  timestamptz not null default now()
);

create index if not exists video_looks_language on public.video_looks (language, video_id);

alter table public.video_looks enable row level security;
-- RLS without policies already keeps anon and authenticated out; drop their
-- default grants too, so turning RLS off would not expose the table.
revoke all on public.video_looks from anon, authenticated;
