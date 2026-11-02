-- word ranks: Jev's ranking of the words of a video or Library item
-- (word_importance.py), saved the first time its word list is opened.
--
-- Both hold {"<word id>": [here, general]}: how much the word helps a learner
-- follow this text, and how useful it is outside it, each 1..5. The
-- missing-words endpoints combine them and mark the key words; the cut-offs
-- live in code. Ranks with an older rubric_version are redone on the next open.
--
--   video_word_ranks          the shared corpus, one row per video, for every user
--   user_media.word_ranks     a Library item's, deleted with the item
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent.

create table if not exists public.video_word_ranks (
    video_id        text primary key,
    language        text not null check (language in ('es', 'de', 'it', 'fr')),
    rubric_version  smallint not null,
    ranks           jsonb not null,
    ranked_at       timestamptz not null default now()
);

alter table public.video_word_ranks enable row level security;
-- Only the API's service role reads or writes it, like video_scores.
revoke all on public.video_word_ranks from anon, authenticated;

-- user_media's RLS already lets a signed-in user read only their own rows,
-- and write none.
alter table public.user_media
    add column if not exists word_ranks         jsonb,
    add column if not exists word_ranks_version smallint;
