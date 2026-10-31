# Langfour on YouTube

Status as of 2026-10-31: plan, nothing built. People learn a language on YouTube by watching
hours of videos they can mostly follow, and they stay for channels they love. This plan makes
Langfour good at both: it knows which videos you can follow, learns which channels you love,
and stays out of the way while you watch. Mockups and charts are in `docs/plans/youtube-plan/`.

| # | Feature | Group | Size |
|---|---|---|---|
| 1 | [Known words that stay honest](#1-known-words-that-stay-honest) | Fix the basics | M |
| 2 | [A watch signal that includes the YouTube app](#2-a-watch-signal-that-includes-the-youtube-app) | Fix the basics | M |
| 3 | [Fit badges on every thumbnail](#3-fit-badges-on-every-thumbnail) | Find | M |
| 4 | [Favourite channels](#4-favourite-channels) | Find | L |
| 5 | [Your feed: a queue per learner](#5-your-feed-a-queue-per-learner) | Find | L |
| 6 | [Steer YouTube's own recommendations](#6-steer-youtubes-own-recommendations) | Find | M |
| 7 | [A watch panel built for flow](#7-a-watch-panel-built-for-flow) | Watch and keep | M |
| 8 | [Core words for a channel or a series](#8-core-words-for-a-channel-or-a-series) | Watch and keep | M |
| – | [Later](#later): index ahead of demand, moment cards, a video graph | | |

## 0. What the numbers say

Measured on every Spanish transcript in `apps/api/data/processed/es` with at least 300 words:
10,908 videos from 1,346 channels. The processed JSON stores every token with its word id, so
nothing had to be re-ingested.

![Median coverage by vocabulary size: shown today vs heard](youtube-plan/coverage-heard-vs-shown.png)

**How to read it.** Picture a set of learners: one knows the 500 most common Spanish words, the
next the 1,000 most common, and so on up to 10,000 (the horizontal axis). For each learner, go
through every video and ask two questions:

- **Grey, shown today:** of the *different* words in this video, what share do they know? This is
  the "% understood" the app shows. The recommender's document-term matrix stores 1 for "word
  appears" (`recommender.py`, `D[i, wid] = 1`), so `que` said 80 times counts once.
- **Blue, heard:** of all the words *spoken*, counting every repeat, what share do they know? This
  is what the learner experiences.

Each line is the median over all 10,908 videos. At 3,000 words the app says 86.5%, but the
learner knows 95.5% of what they hear, which is enough to follow most videos. The gap is widest
for beginners, the people who most need to hear "you can watch this".

| Words known | App shows | Heard | Videos you can follow (95% heard) | Videos the app puts at 95% |
|---:|---:|---:|---:|---:|
| 1,000 | 68.0% | 88.5% | 0.5% | 0.0% |
| 2,000 | 80.4% | 93.3% | 23.2% | 0.2% |
| 3,000 | 86.5% | 95.5% | 59.3% | 1.9% |
| 4,000 | 90.0% | 96.8% | 79.2% | 8.1% |
| 5,000 | 92.3% | 97.6% | 89.1% | 19.5% |
| 8,000 | 95.9% | 98.8% | 98.3% | 64.9% |

`recommend_videos` then sorts by the grey number, highest first. For a 3,000-word learner, the top
20 picks are 98.8% heard, have a median of 5 new words and run 4.9 minutes. The 95–98% band holds
over half the corpus for that learner, at a median of 45 new words and 12.9 minutes.

**With real accounts.** Real learners don't know exactly the top N words, so the same numbers on
the accounts with real Spanish vocabulary:

| Account | App shows | Heard | Videos at 90–95% heard |
|---|---:|---:|---:|
| A learner with 2,449 known words | 74.3% | 89.9% | 48.6% |
| A learner with 1,376 known words | 64.3% | 85.6% | 6.0% |
| A long-standing account, as stored | 62.1% | 68.3% | 0.0% |
| The same, with 45 stuck common words counted as known | 68.9% | 88.2% | 28.2% |
| The same, with every learning word counted as known | 74.6% | 90.4% | 53.0% |

The long-standing account comes out lowest despite the most words. `que`, `y`, `no`, `un`, `lo`,
`por` and 39 other top-300 words are stored as *learning*, from a flashcard import on 2025-05-26,
never reviewed. `user_known_words` leaves learning words out, so those 45 words count as unknown,
and they make up 20% of everything spoken in the corpus. Feature 1 fixes this.

Other things that hold today:

- The channel-page Bookmark button posts to `/youtube/bookmarks`; the API on `main` has no such
  route, so it spins on "Indexing Queued" forever (`youtubeBookmark.ts`, `api-service.ts`).
- A newly ingested transcript reaches recommendations only after `pack_corpus.sh`, an R2 upload
  with a read-write token, and an API restart (`corpus_sync.py`).
- The pipeline keeps 15 slots per channel; indexed channels have a median of 10 usable videos,
  and 418 of 1,346 have 3 or fewer.
- `videos_seen` holds 383 rows from 14 users, with no idea how much of each video was watched.

## 1. Known words that stay honest

*Fix the basics · M · needs 2 for the "heard" evidence*

Every number in Langfour depends on knowing which words you know. Words stuck in "learning" make
every video look harder than it is, so recommendations come out too easy and the badges discourage.

![A one-time prompt offering stuck common words as known](youtube-plan/f1-known-words.png)

*A one-time prompt in the extension popup and on the Vocabulary page. Words you've looked up stay
unticked. The "heard" counts are illustrative; feature 2 is what collects them.*

- **One-time cleanup:** learning words in the top 500 by corpus frequency that were never reviewed
  are offered as known.
- **Ongoing rule:** a learning word heard in 10 or more watched videos without a look-up becomes a
  suggestion, never an automatic change. Accepting goes through the same path as the MCP's
  `set_word_status`.
- **Coverage on words heard:** the matrix stores the count instead of 1. The transcripts already
  have counts, the number of non-zeros doesn't change, and every percentage in the app becomes the
  blue line.
- The same screen can show the known form-versus-root mismatches (`caía`/`caer`).

**Measure:** median heard coverage of the videos people finish. With honest data it should sit
near 95%.

## 2. A watch signal that includes the YouTube app

*Fix the basics · M · needs the learner's approval, per account*

Most watching happens in the YouTube app on a phone, where no extension runs. Google syncs a
learner's watch history across devices, so the history is the one place that also sees phone
watching.

![Watch signal sources, filter and uses](youtube-plan/f2-sources.png)

*Four ways to learn what someone watched, from most precise to most complete. Everything outside
the learning language is dropped on arrival and never stored.*

| Source | What it gives | Limits |
|---|---|---|
| Extension on desktop | Seconds actually played, look-ups | Desktop only |
| `youtube.com/feed/history`, read by the extension with the learner's own sign-in | Every watch on any device; the red progress bar gives a rough share watched | Runs only when the desktop browser is open |
| Google's Data Portability API, scope `dataportability.myactivity.youtube` | YouTube activity, server-side, without a desktop | Restricted scope, so Google's app verification; consent lasts 30 or 180 days; one export per 24 h; supported countries still to check |
| Google Takeout watch-history file | A one-off first import | Manual upload |

The YouTube Data API has returned no watch history since 2016 (the `HL` playlist is empty), so the
Data Portability API is the only official server-side route.

![Per-account approval and a recap of phone watching](youtube-plan/f2-approval-and-recap.png)

*Left: the per-account approval. Right: a recap of phone watching on the Practice page and in the
extension popup the next day. Kept words go to reviews (or RemNote) with a line from the video as
context.*

- 70% played on desktop marks a video watched and replaces the manual "Hide & mark as seen".
- A `watch_events` table: learner, video, watched at, share played when known, source. Own rows
  only, like `user_media`. `videos_seen` becomes a view over it so current callers keep working.
- What it enables: watched marks, feed seeds and "favourite this channel?" suggestions, word recaps
  and next-video suggestions for phone watching, and "heard" evidence for feature 1.

## 3. Fit badges on every thumbnail

*Find · M · needs 1*

From a thumbnail you can't tell whether you'll follow a video, so people click, struggle for two
minutes and leave. Badges answer that before the click, everywhere on YouTube.

![YouTube search with fit badges](youtube-plan/f3-fit-badges.png)

*Badges show heard coverage and new words, coloured by band: green 95–98%, amber 90–95%, red below
90%. The Your level chip dims the rest; unindexed videos show "Add to Langfour" on hover.*

- A content-script observer collects video ids from Home, Search, channel pages and the watch-page
  sidebar as they render. One batched call, `POST /api/videos/fit` with up to 50 ids, returns
  coverage, new words and length; each id is one sparse row times the known-words vector.
- Cached per learner for 12 hours. Selectors live in one module with a daily smoke test against
  youtube.com, since YouTube's markup changes often.
- Editing youtube.com goes against the spirit of YouTube's terms, as many learning extensions do;
  accepted.

## 4. Favourite channels

*Find · L · needs the existing queue*

Learners scroll through recommendations until they find a few channels where they understand the
speaker and like the topics. Those channels carry them for months. Today that discovery is luck,
it stays private, and Langfour has indexed a median of 10 videos per channel.

![Favourite button, channel profiles and the clarity question](youtube-plan/f4-favourite-channels.png)

*"Favourite" sits next to Subscribe and replaces the broken Bookmark button. The channel's
Langfour tab lists channels that learners at your level also favourited. The one-tap question
appears after a learner's first few videos from a channel.*

What a favourite does:

- **For you:** the channel gets the biggest share of your feed (5).
- **For other learners:** favourites add up per channel and level band. "Learners at your level
  also love" lists channels favourited by people who favourited this one, at a similar vocabulary
  size.
- **For the index:** no new system. `video_queue` already drains by `priority`, then `score`. A
  favourite raises the channel's pending rows to the user tier (10), adds its unqueued uploads at
  that tier, and lifts the 15-per-channel cap for that channel.

How a channel is described:

- **From scores every video already has.** `video_scores` holds Jev's rubric for all 11,372 scored
  Spanish videos (`video_quality.py`): A, the grammar level (A1–C1); C, content in the words; D,
  developed thought; E, transferable language. A channel's profile is the median of its videos, so
  it covers the whole corpus with no backfill.
- **From learners:** "Yes, clear / Too fast / Hard accent", asked after a learner's first few
  videos from a channel. The only signal on pronunciation and pace, which a transcript can't show.
- **Country:** from `channels.list` (1 quota unit).

**Measure:** share of learners with at least one favourite after two weeks, and how much of their
watching comes from favourites.

## 5. Your feed: a queue per learner

*Find · L · needs 1; 2 and 4 make it personal*

Everyone draws from one global list sorted by the grey number, which surfaces trivial clips. Each
learner should have their own queue, built ahead of time, leaning towards the channels and topics
they like.

![How a learner's feed is built](youtube-plan/f5-feed-pipeline.png)

*Until a learner has favourites and watch history, the current recommender (with coverage on words
heard) fills the whole feed, and it stays the fallback for any source that runs dry. The shares are
starting values to tune; the mix keeps some discovery even for learners with strong favourites.*

- Rebuilt nightly, and right after a favourite or a finished video.
- Stored in `user_feed` (learner, video, source, position, reason), so the Home shelf, the watch
  panel and the web app read a ready list instead of scoring 11,000 videos per request.

![The feed as a shelf on YouTube Home](youtube-plan/f5-home-shelf.png)

*The main surface: a shelf at the top of youtube.com Home. Each card says which source put it
there.*

## 6. Steer YouTube's own recommendations

*Find · M · needs 2 for the history, 3 for language labels*

On a phone, YouTube's own Home and Up next decide what people watch. If half an account's history
is English, half its feed is too. YouTube's recommendations follow the account's history,
subscriptions and "Not interested" feedback, and the learner controls all three.

![Language labels and YouTube's own feedback buttons on Home](youtube-plan/f6-home-feedback.png)

*Videos in other languages get a plain language label and YouTube's own two feedback buttons one
tap away. The count at the top shows whether the feed is turning Spanish.*

The levers, strongest first:

1. **A learning profile.** A second Google account or a YouTube Brand account used only for Spanish
   and signed in on the phone. The cleanest feed with no tooling; onboarding suggests it.
2. **History cleanup.** With feature 2's history, list recent videos that aren't in the learning
   language. The learner reviews and confirms; the extension removes them through YouTube's own
   "Remove from watch history".
3. **Feedback on Home:** language labels and one-tap "Not interested" or "Don't recommend channel".
4. **Favourite also subscribes,** as an option, since subscriptions weigh heavily.
5. **Settings checklist:** YouTube location set to Spain or Mexico; pause history while watching in
   other languages.

Not this: playing videos in the background to add fake watches. It inflates creators' view counts,
YouTube treats it as fake engagement, and it puts the learner's account at risk.

**Measure:** share of Spanish videos on the learner's Home feed, counted on desktop where the badges
already classify every card.

## 7. A watch panel built for flow

*Watch and keep · M · needs 5*

Learners came to watch. Every stop costs momentum, so the panel keeps the video playing and lines
up the next one rather than adding study tools.

![Watch-page panel with hover meaning and autoplay from the feed](youtube-plan/f7-watch-panel.png)

*Hovering a caption word shows its meaning with the + while the video keeps playing. When the video
ends, the next one from the feed starts after a short countdown, in place of YouTube's autoplay
pick. Nothing is drawn over the player beyond today's caption marking.*

- **Look up without stopping:** a short hover shows the translation and the + in place. A click
  opens today's full popup and pauses, as now.
- **Our autoplay:** on `ended`, the panel starts the next feed video after 8 seconds; it can be
  turned off.
- **Up next from the feed** replaces YouTube's list in the panel. Collapsible, and it remembers.
- No transcript, replay, loop or pause tools. A learner who wants study mode has the reader.

**Measure:** videos and minutes per session with the panel on vs off.

## 8. Core words for a channel or a series

*Watch and keep · M · needs 1, 4*

Nobody preps before a single video. But a channel or a series has a vocabulary of its own: a Clash
Royale channel says *cofre* and *desbloquear* in every video. Learn those once and the whole
channel opens up.

![Core words card for a channel](youtube-plan/f8-core-words.png)

*Real numbers: a learner with 2,449 known words and the 13 indexed videos from BasiCH. The bars
count videos they can follow (90% or more heard). Shown on the channel's Langfour tab after a
favourite, and on a series page in the Library.*

- Core words: unknown words that appear in at least half of a channel's (or series') videos,
  ordered by how often they're spoken, up to 25.
- It pays off for channels with a narrow topic. Across channels with 12 or more videos, the typical
  gain from 25 words was about 2 points of heard coverage, against 9 for BasiCH and a beading
  channel. The card only appears when the gain is real, for example 3 more videos you can follow.
- "Add to my reviews" goes to Langfour's scheduler or RemNote, with a line from the channel as
  context.
- Netflix and Prime series work the same way from the Library's episodes, which carry series and
  season.

## Roadmap

| Phase | Weeks | Features |
|---|---|---|
| Fix the basics | 1–3 | 1 counts in the matrix and stuck-word cleanup · 2 desktop watched mark and history-page read · 3 fit badges · 4 Favourite button and queue bump |
| Feed | 3–6 | 5 per-learner feed and Home shelf · 6 labels, feedback and history cleanup · 4 channel profiles and "also love" · 2 recaps of phone watching |
| Watch and keep | 6–10 | 7 flow panel with autoplay · 8 core words · 2 Data Portability API, if desktop-less learners matter |

Honest numbers and the watch signal come first because everything else reads them. The Favourite
button ships early so likes are piling up when the feed is built.

## Later

- **Index ahead of demand.** Store each video's word counts in Supabase (`video_terms`) so a new
  video is recommendable within a minute instead of after a repack, upload and restart. Then let
  demand (favourites, feed appearances, opens) set queue priority continuously. Until then,
  favourites bumping the existing queue covers the main case.
- **Moment cards.** A saved word returns in review with the 4-second clip it came from, in YouTube's
  embedded player. Only made when Jev judges the moment a good fit: the word in its common meaning,
  a line that stands on its own, short, clean caption timing. Otherwise a plain card.
- **A video graph.** "More like this, 2–3 steps out" needs a feasibility study first. The Data API's
  related-video search was removed in 2023 (to verify); featured channels (`channelSections.list`,
  1 unit) are allowed and cheap; the learner's own sidebar is the best signal but a grey zone;
  calling YouTube's internal endpoints from our servers is out. Co-favourites (4) and co-watching
  (2) can be built regardless.
