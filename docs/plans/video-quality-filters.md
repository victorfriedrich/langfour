# Video quality filters

Status as of 2026-10-29. Rating every corpus transcript with Jev so the recommender stops serving
garbled, off-target and low-content videos. Code: `apps/api/video_quality.py`; table:
`apps/api/sql/video_scores.sql`.

## 0. Where things stand

| Item | State |
|---|---|
| `video_scores` table | applied 2026-10-29, RLS on, service role only |
| Scoring at ingest (`ingest.py run`) | on this branch |
| Recommender skips hidden videos | on this branch; reads scores once at startup |
| Spanish backfill (`scripts/score_videos.py --lang es`) | done 2026-10-29: 10,657 scored, 2,991 hidden (28%); 6 empty transcripts skipped |
| German, Italian, French | not scored: the prompts are Spanish-specific |
| A (grammar) and D (developed thought) | stored, **not used** |

## 1. The problem

The recommender sorts by coverage, the share of a video's distinct words the user knows, highest
first. Among the 200 easiest unseen videos for one test account, a large share was junk: Fortnite
and Minecraft clips whose auto-captions are word salad, English lessons for Spanish speakers,
songs and poems, and reaction videos that say almost nothing without the picture.

## 2. What is rated

One Decisions API request per video (`typesafe/jev-1.13`). Jev reads the raw transcript, whole up
to 3,000 words and as three 1,000-word windows at 20/50/80% beyond that. Each answer is a
probability over the options; scales are stored as the probability-weighted average.

| Key | Question | Options | Used |
|---|---|---|---|
| `integrity` | Is the transcript readable Spanish, or did captioning fail? | clean / patchy / garbled | filter |
| `foreign_lesson` | Is the video teaching a language other than Spanish? | yes / no | filter |
| `sung` | Is most of it sung or recited (song, rap, poem)? | yes / no | filter |
| A `grammar` | CEFR grammar level needed, vocabulary excluded | A1–C1 → 1–9 | **stored only** |
| C `content` | How much meaning the words carry without the picture | 1–10 | floor |
| D `developed` | Whether ideas are developed or only reacted to | 1–10 | **stored only** |
| E `transferable` | Whether the language is useful outside this video | 1–10 | floor |

The exact prompt text is in `video_quality.py`.

## 3. The rule

`video_quality.hidden()` hides a video when any of these holds:

- `p_garbled ≥ 0.6`
- `p_foreign_lesson ≥ 0.9`
- `p_sung ≥ 0.9`
- mean of C and E `< 5`

Ranking is unchanged: the remaining videos are still sorted by coverage. Videos that were never
scored (other languages, a failed request) are never hidden. Thresholds live in code and the table
keeps every probability, so re-tuning needs a restart, not new requests.

## 4. Backfill result (Spanish, 2026-10-29)

| | Videos | Share |
|---|---|---|
| kept | 7,666 | 71.9% |
| low_quality (C+E below 5) | 2,696 | 25.3% |
| garbled | 158 | 1.5% |
| sung | 86 | 0.8% |
| foreign_lesson | 51 | 0.5% |

The floor removes less of the whole corpus (25%) than of the easiest 200 videos (about 40%): the
easiest videos are disproportionately short gaming and reaction clips.

## 5. Evidence behind the choices

Measured during the design session on the 200 easiest unseen Spanish videos for one account, plus
100 videos spread across that account's coverage range.

- **Filters on 200 videos:** 20 garbled (11 of them gaming), 10 foreign-language lessons (9 at
  probability 1.00, all English lessons), 8 sung (5 above 0.98, all correct; the 3 below 0.62 were
  false). With the thresholds above, about 28 are hidden.
- **Floor:** with the filters and a C+E floor of 5, 116 of the 200 remain. The top of the list
  barely changes; the floor mostly removes junk further down.
- **Blind check with Sonnet** on 16 videos: rank agreement 0.89 (C), 0.92 (D), 0.93 (E). C and E
  sit at the same level as Sonnet's scores.
- **Integrity** matched Sonnet's label on 12 of 16 videos and was within one level on all 16.
- **Stability:** repeated runs gave the same label on 95–99% of videos.
- **Cost:** about $0.0002 per video, ~$2–3 for the Spanish corpus.

## 6. What A and D are for (not used yet)

**A, grammar level.** Meant for matching videos to a learner's level once the app knows that
level. Prompt framing was tested at length:

- Telling Jev to "ignore vocabulary" changed nothing.
- Narrowing the question to subjunctive and conditional frequency removed the link to vocabulary,
  but also most of the grammar: rank agreement with a holistic Sonnet rating dropped to 0.50.
- The short holistic prompt now in use agrees with Sonnet at about 0.83.

Grammar level still rises with vocabulary difficulty and transcript length. Part of that is real:
monologues and arguments use harder grammar and harder words than sketches and game chatter. On
these videos it reads about half a level higher than Sonnet at the low end, so treat it as a
ranking rather than an exact CEFR label.

**D, developed thought.** Scores about 2 points above Sonnet on tutorials and lists, which it
counts as sustained explanation. It overlaps C on noisy transcripts, though much less on clean
ones. Possible later use: a preference for stories and arguments.

Vocabulary difficulty is deliberately not asked of Jev. A word-frequency profile (share of a
video's words outside the 2,000 most common) tracks the user's coverage at −0.79; Jev's vocabulary
level only at −0.52.

## 7. Next

- [ ] Restart the API after deploying so the recommender loads the scores.
- [ ] Watch whether hidden videos are missed. `scripts/score_videos.py --report` prints hidden counts per reason.
- [ ] Prompts for German, Italian and French (examples and grammar levels are Spanish).
- [ ] Use A for level matching, once the app knows a learner's level.
- [ ] Average scores per channel and feed them back into `ytpipeline` discovery.
- [ ] Dead air ≥ 10 s and target-language share from caption timings, at ingest.
