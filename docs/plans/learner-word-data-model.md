# Learner–word data model

Status as of 2026-10-29. Steps 1, 2, 2a and 4 are merged (PR #54) and applied to the live
database; the 17 dropped functions' definitions are kept in `archive.dropped_functions`. **Step 3
is implemented** on branch `feat/langfour-provider` (`sql/langfour_provider.sql`), not applied
yet; it has to land before ChatGPT practice goes to users. Covers how Langfour stores what a user does
with a word: the decisions they make, the reviews from any flashcard system, and evidence from
outside them (ChatGPT practice through the MCP server, the reader, videos). Written while
designing the MCP server. Section 2a lists improvements to the RemNote plugin's speed and
reliability found along the way.

**Langfour schedules reviews itself; RemNote is an optional integration**, and Anki may become
another. Every user starts on Langfour's scheduler, and only some connect an outside app. The data
model follows from that: Langfour's scheduler is the base every word has, outside apps are
providers added on top, and features such as ChatGPT practice must work for a user who never
connects one.

Database numbers below are from the live project (`Lang`) on 2026-10-29. Function lists come from
`pg_proc` in the live database, not from the schema map, and callers from `origin/main`.

## 0. Where things stand

| Table | Holds | Rows | Problem |
|---|---|---|---|
| `userwords` | the user's decision on a word **and** Langfour's SM-2 schedule | 315,324 | every learning word (5,231) has a schedule, since `next_review_due_at` defaults to `now()`, but only 654 rows were ever reviewed; on known words, most of the rows, the five SM-2 columns are unused |
| `flashcardtests` | Langfour's own reviews, right/wrong | 890 (30 users ever, 2 in the last 60 days; all `test_type = 'flashcard'`) | a second review table every reader has to combine with `srs_reviews` by hand; `tested_at` has no time zone |
| `srs_notes` / `srs_cards` / `srs_reviews` | RemNote's notes, cards and review history | 2,396 cards, 4,679 reviews (1 user) | none; this is the model the rest should follow |
| `userwordinteraction` | exposure (word, `location`, `seen_at`) | **0**, never written | read by `get_user_counts_with_wordforms`, whose "seen" count is always 0 |

158 users; one (the author) reviews in RemNote. Everyone else is on Langfour's own scheduler.

The cost of combining review tables by hand is already visible: `word_progress` notes that
`get_user_counts_with_wordforms` "only sees Langfour's" reviews and misses RemNote's.

## 1. Target design

One job per table:

```
DICTIONARY     words, wordforms                                         unchanged

RELATIONSHIP   userwords(user_id, word_id, status, source, created_at)
               status: learning | known | disabled   -- the user's decisions only

SCHEDULING     srs_notes(user_id, word_id, provider, external_id, created_at, removed_at)
(any provider) srs_cards(note_id, external_id, kind, next_due_at)
               srs_card_sm2(card_id, ease_factor, repetition, interval_days)   -- Langfour cards only
               srs_reviews(card_id, reviewed_at, outcome)
               provider: langfour | remnote (| anki later)

EVIDENCE       word_events(id, user_id, word_id, kind, source, occurred_at, context)   -- append-only
               kind: saved | lookup | exposure | recall_correct | recall_wrong

DELIVERY       srs_outbox(event_id, card_id, status, decided_at, reason)
               status: pending | applied | skipped

DERIVED        user_known_words (view); later word_knowledge
```

### Providers

- **Langfour is the base scheduler.** Every learning word has a Langfour note and card, for every
  user, whatever else is connected. Cards are created by a trigger on `userwords`, with no
  condition on the provider.
- **An outside app is a provider added on top.** While it's connected, it has its own notes and
  cards for the same words (`srs_notes.provider`), and `userdata.review_provider` says which
  scheduler is active. One user, one active scheduler.
- **Disconnecting needs no migration.** The Langfour cards are still there, and Langfour's
  schedule takes over again.
- **Outside apps are pull-based.** RemNote has no backend API or webhooks, and neither does Anki;
  both need code running inside the app (the RemNote plugin, an Anki add-on) that comes to
  Langfour for work. `srs_outbox` and the inbox pattern (2a) serve any such provider. Langfour's
  own scheduler applies results immediately and needs neither.

### Rules

- **`userwords` stores decisions, never knowledge.** Whether a word is known stays computed
  (`user_known_words`), so a forgotten word drops out on its own.
- **One review table.** Langfour is a provider like RemNote. A right answer is stored as `good`,
  a wrong one as `again`.
- **The event log is never updated or deleted from.** Delivery state lives in `srs_outbox`, which
  only has rows for recalls meant for a card. Exposures, which will far outnumber recalls, never
  get one.
- **No counting twice.** A recall that was applied to a card exists as a review. Scoring reads
  `srs_reviews` + `word_events`, minus recall events whose outbox row is `applied`. Skipped
  recalls stay in as evidence from outside the flashcard systems.
- **Exposure counts only what the user chose to read or hear** (text they asked ChatGPT for, not
  every word ChatGPT wrote). If the reader ever logs every word on every page, store that as daily
  counts in its own table then, not in `word_events`.

### Not doing

- One polymorphic "interactions" table: reviews are per card with four grades, events per word
  with different kinds; merging them means nullable columns and per-type checks.
- A stored `known` flag on `userwords`.
- A scoring model now. Collect events first; `word_knowledge` comes once there is data to fit.

## 2. Migration order

Each step is shippable on its own. All SQL goes through the Supabase connector, like the other
files in `apps/api/sql/`.

Order: 1, 2, 2a and 4 (built, PR #54), then **3 before `record_practice` is offered to users**.
Step 2 covers RemNote users only, because Langfour users have no `srs_cards` rows until step 3;
their recalls are logged but don't change their schedule. Since Langfour's scheduler is the
default, that leaves most users without the feature, so step 3 comes before any rollout. It then
applies their recalls against real cards, with no interim code path to remove.

### Step 1: `word_events` (replaces `userwordinteraction`)

**Schema** (`apps/api/sql/word_events.sql`):
- `word_events`: `id bigint identity` PK, `user_id uuid` → `auth.users`, `word_id int` → `words`,
  `kind text` (check: the five kinds), `source text` (check: `chatgpt, reader, video, extension,
  web`), `occurred_at timestamptz default now()`, `context jsonb`.
- Indexes `(user_id, word_id)` and `(user_id, occurred_at)`.
- RLS: `select_own` and `insert_own` only. No update or delete policy, and revoke `update, delete`
  from `authenticated`.
- `context` for `saved`: `{site, title, episode, sentence}`. This is the per-save context the
  Netflix use cases need.
- Drop `userwordinteraction` (0 rows; its RLS policies and FKs go with it).

**Functions touched**

| Function | Change | Caller |
|---|---|---|
| `get_user_counts_with_wordforms(_word_id)` | `seencount` from `word_events` (`kind = 'exposure'`) instead of `userwordinteraction`; `reviewcount` from both review tables, which fixes the RemNote gap now instead of in step 3 | `useWordInfo.ts` → `WordInfoPopup`, `CompactWordInfoPopup` |
| new `record_word_events(rows jsonb)` | security invoker insert, user id from `auth.uid()` | later the extension and reader; the MCP server writes through the API |
| `merge_roots(payload)` | also moves the merged root's `word_events` to the surviving root. The one update the log allows: a dictionary correction, run with the service role | `apps/api/scripts/review_flagged.py` |

**Writers, later and separately:** the extension's save path writes `saved` with context; the
translation popup writes `lookup`.

### Step 2: `srs_outbox` and `record_practice`

**Prerequisite:** on a throwaway RemNote knowledge base, check that
`Card.updateCardRepetitionStatus(score)` (plugin SDK 0.0.46) moves `nextRepetitionTime`, and how
the added review looks in `repetitionHistory` (`isCram`, `date`). If it doesn't reschedule,
RemNote practice can't be fed from ChatGPT and this step stops at logging. This needs a RemNote
account, so it's done by hand; the code below is built on the assumption that it reschedules.

**Reviews from ChatGPT can't be tagged inside RemNote.** `updateCardRepetitionStatus` takes only a
score, so there is no way to set `pluginData` on the review it adds. RemNote's Terms (section 10)
let it use anonymised review history for research and model training, so these reviews end up in
that data looking like any other. That's the main reason only conservative grades are applied.
On Langfour's side they stay identifiable: the plugin reports the date of the review it added, and
`srs_outbox.applied_review_at` together with `card_id` is that review's key in `srs_reviews`.

**Schema** (`apps/api/sql/srs_outbox.sql`):
- `srs_outbox`: `event_id bigint` PK → `word_events` on delete cascade, `card_id bigint` →
  `srs_cards` on delete set null, `outcome text` (check: `again, good`), `status text` (check:
  `pending, applied, skipped`), `decided_at timestamptz`, `reason text`, `applied_review_at
  timestamptz`.
- Partial index on `(card_id) where status = 'pending'`.
- RLS: `select_own` through `word_events`. Writes only through the API (service role); the plugin
  talks to the API with its sync token, like the rest of the sync.

**Flow**
1. MCP `record_practice(results[])`: one call per practice session, confirmed by the user. Writes
   one `recall_correct`/`recall_wrong` event per result. For a RemNote user, it also writes an
   outbox row for each word that has a live card of the right kind: recognising the word →
   `forward`, producing it → `backward`. Cloze cards are skipped.
2. When the inbox (section 2a, item 2) reports practice waiting, the plugin takes the sync lease,
   fetches the rows (`GET /sync/remnote/practice`), applies each result to its card, pushes those
   cards' reviews, and reports `applied` with the review's date, or `skipped` with a reason
   (`POST /sync/remnote/practice`). All under one lease, so two devices never add the same
   review. Before changing a card the plugin saves how many reviews it had, and decisions are
   kept in plugin storage until the report succeeds: an attempt cut off at any point is
   reconciled against the card's history instead of adding the review twice, and an applied
   result's review is uploaded again before it's reported. No full sync.
3. Langfour users: event only, no outbox row, until step 3.

`practice.py` currently checks `review_provider == 'remnote'` by name. Step 3 makes it
provider-neutral: the active scheduler is Langfour → apply now; an outside app → queue in
`srs_outbox` for it.

**What gets applied:** nothing while the Rem's flashcards are turned off (checked on the live Rem).
Otherwise wrong → `again`, always; right → `good` (never `easy`), only if the card is due or
overdue, judged by the plugin on the live card. At most one result per card per day:
within one `record_practice` call a wrong answer wins over a right one; a later call the same day
gets no outbox row for that card. Everything else is `skipped`, and the event stays as evidence.

**Functions touched:** none of the existing ones. New: `apps/api/practice.py`,
`GET`/`POST /sync/remnote/practice` in `apps/api/remnote_sync.py`, `apps/remnote-plugin/src/inbox.ts`,
and the MCP server (`apps/api/mcp_server.py`, served at `/mcp`, bearer token only until OAuth).

### 2a. Alongside step 2: making the RemNote integration faster and more reliable

From reading the plugin on `main` (`src/widgets/index.tsx`, `src/live.ts`, `src/sync.ts`). In
order of value:

1. **Publish the plugin as unlisted.** It still loads from "Develop from localhost", so it only
   runs while `npm run dev` is running on the machine with RemNote open: no syncing on the phone
   (`enableOnMobile` is set but can't take effect), and nothing when the dev server is off. An
   unlisted upload is always installed, on desktop and mobile. RemNote's review requires a public
   repository; `repoUrl` already points to the public `langfour` repo. To check: whether
   reviewers accept a plugin in a monorepo subfolder, since `npm run validate` expects the plugin
   at the root of its own repository. If not, mirror `apps/remnote-plugin` into a small public
   repo.

   What RemNote's Terms of Service (updated 2025-03-28) and plugin docs say about this:
   - **Automation is allowed through approved plugins.** Section 6.1 bans "repetitive automated
     actions that RemNote has not been explicitly designed to allow", except approved plugins. A
     plugin loaded from localhost isn't approved, which is one more reason to publish it.
   - **Integrating into another product needs permission.** Section 6.1: you "can't integrate
     RemNote into another software product without our permission". Low risk for personal or free
     use. If Langfour charges or offers the sync widely, ask in the submission and get it in
     writing.
   - **The README must say what leaves RemNote.** The plugin docs require plugins that send data
     to a third party to state it clearly. Name it plainly: the words, review history and due
     dates go to Langfour.
   - **Plugins that resemble paid features aren't admitted to the marketplace.** RemNote sells AI
     features. Leave ChatGPT practice out of the first submission's description; it's a Langfour
     feature that happens to add reviews.
2. **Check for new work at the moments that matter, instead of waiting for the hourly sync.**
   Today a word saved in Langfour (from Netflix, the reader, ChatGPT) becomes a card only when
   RemNote starts, at the hourly sync, or when the progress page is opened. Add
   `GET /sync/remnote/inbox`, returning `{pending_words, practice}`: two counts, so it's cheap and
   needs no lease. The plugin checks it:
   - **when a review session starts** (`AppEvents.QueueEnter`), so ChatGPT results are on the
     cards before they're shown;
   - at startup and when the progress page opens (both already sync);
   - **every 10 minutes** while RemNote is open, for newly saved words.

   With pending words, it runs an ordinary (incremental) sync, which creates their cards; with
   practice waiting, it applies it as in step 2. The hourly sync stays as the safety net.

   **Not a push.** RemNote has no backend API or webhooks ("We currently don't host a backend
   API"), so nothing can reach a closed RemNote. While it's open, a server-sent "doorbell" (SSE
   from the API, rung by Postgres `NOTIFY`, the plugin then fetching as above) would cut the wait
   to seconds. It costs long-lived connections on Koyeb, a streaming response through the
   `BaseHTTPMiddleware` auth layer, and reconnect logic, and the plugin docs don't say whether a
   sandboxed plugin may hold such a connection. Only worth it if seconds ever matter.
3. **Don't drop failed live pushes.** In `live.ts`, any error other than `SyncBusyError` (offline,
   API restart, timeout) clears the batch, and those answers wait for the next full sync, up to an
   hour later or the next start. Keep failed Rem ids in a retry set with backoff (30 s, 2 min,
   10 min), stored with `plugin.storage` so a reload doesn't lose them.
4. **Keep the "synced X ago" label honest.** It already exists: `vocabulary/SchedulerLabel.tsx`
   shows `api_tokens.last_used_at` and turns amber after 2 days. Every authenticated request
   updates that column (`auth.py`), so once the inbox is checked regularly it reads "synced a few
   minutes ago" whenever RemNote is open, even if syncs keep failing. Record when a sync run last
   *completed* in `userdata.remnote_last_sync_at`, set by the sweep every run sends at its end
   (`run()` in `src/sync.ts`; live pushes also take and release the lease, so release time won't
   do), and show that instead.

Items 1 and 3 don't depend on anything in this plan. Item 2 is the poll step 2 needs, and item 4
comes with item 2.

### Step 3: Langfour as a provider

**Implemented** (`apps/api/sql/langfour_provider.sql`, branch `feat/langfour-provider`). Langfour's
scheduler is the default every user starts on (see the top of this plan), so this step is what
makes ChatGPT practice, and any later feature built on cards, work for most users. It also gives
one review table, with Langfour and any outside app as providers.

**Checked before applying:** on live data, read-only, the backfill would write 5,333 notes and 899
reviews, and the known-words rule over the new tables accepts exactly the same words as the old
one over `userwords` (2 learned through Langfour reviews, none gained or lost). The whole
migration was also run, twice, on a local Postgres with main's schema and seeded users.

**Apply in this order:** `langfour_provider.sql`, then re-apply `known_words.sql`,
`word_progress.sql`, `word_events.sql` and `word_status.sql`, then deploy the web app (it stops
calling `insert_flashcard_test`) and the API. The old web app keeps working in between: its
`insert_flashcard_test` call only adds a row to the now unread `flashcardtests`.

**Bigger than first estimated.** The first version of this plan counted 654 schedules: the
`userwords` rows that were ever reviewed. But `next_review_due_at` defaults to `now()`, so
**every learning word has a Langfour schedule**: 5,231 learning words across 65 users, 4,647 of
them never reviewed. Langfour's review session finds due words through that column, so moving to
`srs_cards` means:
- a Langfour note and card for every learning word of every user, not only the reviewed ones,
  and for RemNote users too (Langfour is the base scheduler);
- a trigger on `userwords` (insert, and status changing to `learning`) that creates the card,
  with no condition on the provider, because words are saved through many paths:
  `move_words_to_userwords`, `initialize_account`, imports, the API's media and flashcard
  imports, `set_userwords_status`;
- `practice.py` deciding by the active scheduler instead of checking for RemNote by name.

**Data to move:** 5,231 learning words' schedules and 890 `flashcardtests` rows (688 distinct
words). Words that also have a RemNote note (232 of the reviewed ones; the author switched
providers) get a second note with `provider = 'langfour'`, which the unique
`(user_id, provider, word_id)` allows.
8 `flashcardtests` rows have no `userwords` row any more and can't hang off `srs_notes`; drop
them.

**Schema**
- `srs_notes.provider` check adds `langfour`; `external_id` becomes nullable, required when
  `provider = 'remnote'` (check constraint).
- New `srs_card_sm2(card_id` PK → `srs_cards` on delete cascade, `ease_factor numeric default
  2.5`, `repetition int default 0`, `interval_days int default 1)`. The due date stays in
  `srs_cards.next_due_at`.
- Backfill: per learning `userwords` row, one note, one `forward` card (`next_due_at` from
  `next_review_due_at`), one `srs_card_sm2` row. Each `flashcardtests` row becomes an
  `srs_reviews` row (`tested_at at time zone 'utc'`; `true` → `good`, `false` → `again`).
- After the app has run on the new tables for a while: drop `flashcardtests`, drop `ease_factor`,
  `repetition`, `interval_days`, `last_reviewed_at` and `next_review_due_at` from `userwords`, and
  make `userwords.created_at` a `timestamptz`.

**Functions touched**

| Function | Change | Caller on `main` |
|---|---|---|
| `update_spaced_repetition(_word_id, _test_result)` | write `srs_reviews` + `srs_card_sm2` + `srs_cards.next_due_at`; create the note and card on a word's first review | `updateFlashCardInfo.ts` → `FlashcardSession`, `MemoryMatchGame`, `CompactWordInfoPopup` |
| `insert_flashcard_test(_word_id, _test_type, _test_result)` | no longer called: `update_spaced_repetition` records the review. Dropped with `flashcardtests` | `updateFlashCardInfo.ts` |
| `user_known_words` (view) | the Langfour branch becomes the same per-card rule as RemNote's, over `srs_*`, for learning words only (a turned-off word is neither learning nor known; no word was affected on 2026-10-29) | recommender, Vocabulary page, `classify_words`, `my_word_statuses`, `known_words_summary`, `get_known_words_page` |
| `word_progress(word_id_param)` | reviews and due date from `srs_*` only; output shape unchanged | `backgroundScript.ts` (extension) |
| `get_learning_words` (the overload left after step 4) | due date from `srs_cards`, review counts from `srs_reviews` | `useLearningWords.ts`, `LearningWordsTable.tsx` |
| `get_userwords_filtered(language_filter, due_type, page_size, p_source)` | due date from `srs_cards` | `useOverdueWords.ts` → `LearningWordsTable`, `vocabulary/page.tsx` |
| `get_user_counts_with_wordforms(_word_id)` | `reviewcount` from `srs_reviews` only (step 1 already counts both tables) | `useWordInfo.ts` |
| `initialize_account` (2 overloads) | unchanged for now: it still writes `next_review_due_at`, which the trigger reads when it creates the card. Changed when the columns are dropped | `useInitializeAccount.ts` |
| `merge_roots(payload)` | where the user has a Langfour card for both roots, the target's card takes the source's reviews, and its whole schedule (due date, ease, repetition, interval together) when the target is new to the user or the source is strictly further along; the source's Langfour note goes, so the unique `(user_id, provider, word_id)` holds | `apps/api/scripts/review_flagged.py` |

**Recalls for Langfour users:** once their cards exist, `record_practice` applies each result in
the same request, through `srs_langfour_practice`: the review, the schedule change and its outbox
row (`applied`, or `skipped` when not due or the word is turned off) in one transaction, keyed by
the event, so a failure part-way can't leave a review without its record for a retry to apply
again. The once-a-day rule is unchanged, and the scoring rule (reviews + events, minus applied
recalls) is the same for every provider. Recalls
logged before step 3 stay as events and are not applied afterwards.

**Switching schedulers:** a RemNote user's Langfour cards keep their old due dates while RemNote
schedules, so on disconnect many would come up at once. When `revoke_token` hands reviews back to
Langfour, copy each RemNote card's `next_due_at` onto the word's Langfour card, so the schedule
carries over instead of flooding the review session.

**App code reading tables directly**
- `apps/web/src/app/hooks/usePracticeProgress.ts`: reads `userwords.next_review_due_at` for
  Langfour users, and `srs_notes` without a provider filter. Read `srs_*` for both, filtered on
  the user's `review_provider`.
- `apps/api/remnote_sync.py`: already filters every `srs_notes` query on `provider`; no change.
- `apps/extension/src/messages.ts` types `word_progress`'s `last_reviewed_at`; no change if the
  output shape stays.

### Step 4 (any time): drop functions nothing calls

No caller on `main` in `apps/` (web, API, extension, plugin). Check the Supabase API logs for
calls from old deployed clients before dropping.

| Function | Touches |
|---|---|
| `get_overdue_words`, `get_top_words_by_due_date`, `get_user_words`, `get_userwords_for_review` | SM-2 columns |
| `get_user_words_with_cursor`, `get_user_words_with_tests` (3 overloads) | `flashcardtests` |
| `get_streak_data`, `get_revision_counts_by_language`, `words_known_by_date`, `unique_learned` | `flashcardtests` |
| `recall_efficiency_last_7_days` | `flashcardtests`; its hook `useRecallEfficiency.ts` is imported nowhere |
| `get_learning_and_unknown_words` | SM-2 columns |
| `get_learning_words`, the 3 overloads the web doesn't call | `flashcardtests`, SM-2 columns |

Dropping these before step 3 means step 3 has fewer functions to rewrite.

## 3. Open decisions

- **`usertranslations`:** 0 rows, but `add_custom_translation` writes it and about ten functions
  left-join it. Keep or drop is separate from this plan.
- **Event sources:** the `source` check list above is a first guess. Add values when a writer
  needs one.
- **Exposure from the reader and videos:** not designed yet. Decide raw events vs daily counts
  when there's a writer.
- **Anki as a provider:** not designed. To check first: whether an Anki add-on can record a review
  on a card the way RemNote's `updateCardRepetitionStatus` does (AnkiConnect alone only works on
  the same machine, so an add-on is the likely route); how card directions map to Anki note types
  (`srs_cards.kind`); and whether the `/sync/remnote/*` endpoints become provider-generic
  (`/sync/{provider}/*`) or Anki gets its own set. The tables need only `anki` added to the
  provider check.
