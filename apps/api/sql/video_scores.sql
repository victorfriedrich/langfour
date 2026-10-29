-- video_scores: Jev's rating of each corpus transcript (video_quality.py).
--
-- One row per video, written when ingest.py finishes a transcript and by
-- scripts/score_videos.py for the existing corpus. The recommender reads it
-- at startup and skips videos video_quality.hidden() rejects: garbled
-- captions, lessons for another language, songs and poems, and videos whose
-- mean of content and transferable is below the floor. The thresholds live
-- in code, so they can be re-tuned from these columns without new requests.
--
--   integrity          clean | patchy | garbled (most likely label)
--   p_garbled,
--   p_foreign_lesson,
--   p_sung             probability of the rejecting answer
--   grammar            A: CEFR grammar level, A1..C1 as 1..9   (not used yet)
--   content            C: content in the words, 1..10
--   developed          D: developed thought, 1..10              (not used yet)
--   transferable       E: transferable language, 1..10
--   jev                every question's raw probabilities
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent. Only the API's service role reads or writes it.

create table if not exists public.video_scores (
    video_id         text primary key,
    language         text not null check (language in ('es', 'de', 'it', 'fr')),
    rubric_version   smallint not null,
    integrity        text not null check (integrity in ('clean', 'patchy', 'garbled')),
    p_garbled        real not null,
    p_foreign_lesson real not null,
    p_sung           real not null,
    grammar          real not null,
    content          real not null,
    developed        real not null,
    transferable     real not null,
    jev              jsonb not null,
    scored_at        timestamptz not null default now()
);

create index if not exists video_scores_language on public.video_scores (language, video_id);

alter table public.video_scores enable row level security;
-- RLS without policies already keeps anon and authenticated out; drop their
-- default grants too, so turning RLS off would not expose the table.
revoke all on public.video_scores from anon, authenticated;
