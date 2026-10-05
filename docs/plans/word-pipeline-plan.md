# Ingestion and dictionary plan

Status as of 2026-10-03. Covers the work agreed in the long session that started with the
YouTube quota question: video discovery, video → text, and text → tokens (the dictionary).

## 0. Where things stand

| Item | State |
|---|---|
| PR #12: cheaper `expand`, 30-day refresh, caption fetching | merged |
| PR #26: RemNote plugin + web pages onto `main` | merged |
| PR #27: `select --push` syncs the queue instead of stacking | merged |
| PR #28: prefer YouTube's automatic captions | closed, superseded by #31 |
| PR #29: 8-minute minimum video length | **open** |
| PR #30: `yt-dlp` audio download | **open**, superseded by #31 (contains the same commit) |
| PR #31: Whisper in pieces cut at quiet points, Whisper as default | **open**, verified end to end |
| Forms saved with an article (`el popis`, `los morrazos`) | **done**: 616 fixed (514 renamed, 102 duplicates deleted), backup in `wordforms_backup_20261003_articles` |
| Jev audit script | draft on branch `feat/word-audit-jev`, not committed; still uses the LLM router, must be rewritten for the Decisions API |

## 1. Video → text

### 1.1 Merge #29 and #31, close #30
- **#29:** 22% of the Spanish selection (7,598 videos) was under 2 minutes, and 60% under 8. `score()` never penalises short videos, so Shorts outranked real ones on view count. The old Selenium scraper never saw Shorts (it read the Videos tab), so the gap appeared when the pipeline replaced it.
- **#31:** Whisper on the whole file dropped 6–12% of words, whole sentences at a time. DeepInfra cuts audio into fixed 30-second windows, and Whisper stops each window early. Pieces of 15–28 s, cut at the quietest moment and sent all at once, fixed it on 6 test videos:
  - missing words 0.5–4.7% instead of 3.7–12.3%;
  - long gaps 4 instead of 27;
  - fewer wrong words than YouTube's automatic captions on most videos, plus punctuation;
  - about 10 s and $0.004 per 20-minute video.

  Captions are now only the fallback; they're unpunctuated, and YouTube rate-limits caption requests under heavy use (we hit HTTP 429 once).
- **#30** is contained in #31.

### 1.2 Speed up word processing in `nlp_processing.py`
After transcription, ~95% of a video's ingest time (9–14 min per video) is adding new words. Each unknown word gets 2–3 sequential `MODEL_SMART` calls, and most come back empty at the token limit (`finish_reason=length`) and are retried.
- Turn reasoning off and raise `max_tokens`, as was done for `classify`.
- Give `generate_alternatives` the same retry and structured-output path as the other calls.
- Process a video's new words in parallel (about 8 at a time).

Expected result: about 1 minute per video instead of 10–14.

### 1.3 Fix missing translations when adding words
84% of the roots added by the last 50 videos (107 of 128) have no translation, and 24% of all Spanish roots (17,225) lack one. A failed `verify_and_translate` call is saved as `None` without a retry. Translation becomes its own step: a chat model writes it, and Jev checks it with one yes/no question.

## 2. Discovery and the queue

- **Finish `expand` for Spanish:** about 900 channels, roughly 23k quota units (~3 days at the 10k daily quota). Run with `caffeinate -i` and `--budget` below the day's remaining quota. Only run it from a checkout that has #12 merged; the old `main` code charged 101 units per channel.
- **Push the selection** with `select --lang es --push` after #29 and #31 are merged. Dry run with #29: 2,144 channels, 25,087 videos.
- **R2 upload:** packing the corpus for the recommender needs a read-write R2 token. The one in `apps/api/.env` is read-only by design.

## 3. Text → tokens: the dictionary

### 3.1 Cache: the junk root wins today (highest value, ~10 lines)
- **The bug:** the lookup cache loads roots in ascending ID order, and for a form shared by several roots the *last* one wins. It ignores root-level `flagged`/`cognate`.
- **Effect:** 15,446 Spanish forms are shared between roots, usually a real root plus a junk copy created later. Today `editaron` links to the English root *edit*, `estudió` to the misspelt *estudar*, and `preguntado` to *question*.
- **Fix:** when a form belongs to several roots, prefer the one that isn't invalid, with the older one as tie-break. This fixes every new transcript immediately.

### 3.2 One `status` column instead of `flagged` + `cognate`
- **Why the old marks don't work:**
  - `flagged=true` on roots is mostly false alarms (*el coche*, *la población*). Only 13 of 6,373 flagged Spanish roots actually have a flagged form.
  - `cognate='invalid'` (52% of Spanish roots) is about half right.
  - Neither mark stops a root from being linked.
  - `cognate` holds nothing except `'invalid'` in any language, so the "Include cognates?" setting has no data behind it.
- **New column on both `words` and `wordforms`:** `status` in `unverified | valid | flagged | invalid`, plus `status_reason` and `audited_at`, and Jev's raw probabilities so thresholds can be re-tuned without new calls.
  - Everything starts as `unverified`; the old marks aren't carried over.
  - Linking rule: link unless `invalid`.
- **Readers to switch:**
  - the cache, and the word-adding path;
  - SQL functions `get_known_words` and `get_words_with_wordforms_cursor`;
  - web: `WordValidation.tsx`, `WordCategories.tsx`, `useWordDetails.ts`;
  - `scripts/language_flagging.py`.
- **Drop `flagged` and `cognate`** once nothing reads them.

### 3.3 Code rules before any model runs
- **Delete forms that contain a space:** 18,738 Spanish forms like *he vituperado*, *os querelláis*, *ele/ela/você endereça*. Transcripts are split into single words, so these can never match. They also make the audit more expensive.
- **Noun roots carry their article;** nouns that take either article use `el/la` (*el/la artista*).

### 3.4 Jev audit
Jev (`typesafe/jev-1.13`, pinned) is a decision model on OpenRouter's Decisions API (`POST /api/alpha/decisions`). It returns probabilities, not text. It costs $0.042 per million input tokens and output is free: about $0.00005 per root, **about $4 for all 73k Spanish roots**, ~20 min at 32 in parallel.

The earlier run through `typesafe/jev-router` was *not* Jev. The router passed requests to DeepSeek and Gemini, which is why it cost ~25× more.

- **One request per root:** state = root + forms (no translation). Questions:
  - one choice (valid / questionable / invalid);
  - one yes/no on the root;
  - one yes/no per form ("is this a form of this root").
- **Rules, measured against my labels of the 128 roots from the last 50 videos:**

  | Rule | Status | On the sample |
  |---|---|---|
  | p_valid > 0.7 | `valid` | 25 roots, 1 minor error (*el matamosquito*) |
  | p_invalid ≥ 0.7 **and** root score < 0.1 | `invalid` | 28 roots, 1 minor error (*austro*, missing article) |
  | everything else | `flagged` | ~57% of roots; Jev can't separate real words from junk here |
  | a form scoring < 0.3 | form `flagged` | caught `rumbadon`; 1 of 363 good forms falls below |

  Jev never called junk valid. Its weakness is calling real words invalid (*la panera* at 0.96, *la gragea*, *el don*).
- **Tell Jev that adverbs, pronouns and conjunctions have no forms.** 27 of 35 form-less roots are junk, so Jev reads an empty list as a junk signal and underrates *os*, *maduramente*, *hipócritamente*.
- **Cost and speed:**
  - keep per-form question text short (it's ~70 tokens per form today);
  - skip forms that 3.3 deletes;
  - make the run resumable, appending one line per root.

### 3.5 Review of `flagged` (Claude, later)
I read every `flagged` root and form and set `valid` or `invalid` with a reason. Policies agreed so far:
- **Diminutives and augmentatives** become forms of their base root: *bellotita* → *la bellota*, *barrigota* → *la barriga*, *güerito* → *güero*.
- **Typos and inflected forms stored as roots** become forms of the right root: *exotica* → *exótico*, *mitica* → *mítico*, *vidios* → *video*, *la sudara* → *sudar*, *consiguío* → *conseguir*, *dibuhame* → *dibujar*.
- **Correct forms under the wrong root** (*adulador* under *adular*) move to the right root.
- **Names, other languages and stretched-out sounds** stay `invalid`.
- **Old spellings and regional forms** (*vió*, *decime*) count as valid.

### 3.6 Merge junk roots into their real counterparts
**Why:** past videos created English and misspelt roots that duplicate a real root's forms (*edit* / *editar*, *estudar* / *estudiar*, *question* / *preguntar*). The processed transcripts store root IDs, so old transcripts link to the junk root. User tables may reference it too.

**Why not just delete:** all six tables that reference `words` cascade on delete (`userwords`, `userwordinteraction`, `flashcardtests`, `usertranslations`, `languagelevels`, `wordforms`). Deleting would silently erase users' saved words and review history.

**Steps:**
1. For each `invalid` root, find the `valid` root it shares the most forms with. High overlap means it's the merge target.
2. Move user rows to the target root without creating duplicates.
3. Move forms the target lacks, and delete the duplicates.
4. Keep the junk root `invalid`.
5. Re-resolve the old transcripts with `scripts/reparse.py`.
6. Roots with no counterpart that are just misspelt (*el márgen* → *el margen*) are renamed in the review pass.

### 3.7 Rework the add path so junk stops being created
In the last 50 videos, names, English, Portuguese and German words with full form sets got in, along with stretched-out sounds (*smosh*, *the friendzone*, *endereçar*, *bergen*, *chaaaan*). `verify_language` doesn't filter them.
- **Check the proposed root with Jev** before creating it (one request).
- **Check whether the token or its proposed root's forms already belong to a valid root,** and attach the token there instead of creating a duplicate root.
- **Write `status` at insert time** from the same audit.

### 3.8 Cleanup, after the merge
- Delete `invalid` roots that nothing references any more.
- Fix junk `language` values on `words`: rows whose language is a video ID (`EdXU1r7f6JY`, `jx2R84gaOeE`) or `MANUAL_TRANSLATION`.
- Drop `wordforms_backup_20261003_articles` once the data is confirmed right.

### 3.9 Postponed
Words with several correct roots (*vino*: wine, or "came" from *venir*; *viste*: from *ver* and *vestir*). The audit must not flag a form just because it also belongs to another root.

## 4. Suggested order

1. Merge #29 and #31.
2. Cache fix (3.1).
3. Word-processing speed and translation fixes (1.2, 1.3).
4. Status migration (3.2), then the code rules (3.3).
5. Jev audit script on the Decisions API (3.4); run on Spanish.
6. Claude review of `flagged` (3.5).
7. Merge junk roots and reparse transcripts (3.6).
8. Add-path rework (3.7).
9. Cleanup (3.8).
10. Push the Spanish queue, finish `expand`, ingest.

Steps 1–3 are independent of each other. Step 3 is worth doing before any large ingest run, since it's the bottleneck.

## 5. Housekeeping
- Your checkout at `/Users/victorfriedrich/Langfive` is on `feat/remnote-sync`, 15+ commits behind `main`, with uncommitted changes. Running scripts from it runs old code (this happened once: 7 videos failed on `get_transcript`). The RemNote work is merged, so compare the uncommitted changes with `main` before switching.
- The label sheet artifact (`claude.ai/artifact/3YSf2vqYjwuGxWex2t8Udn`) is no longer needed and can be deleted.
- Session worktrees live under the scratchpad (`pr12`, `queue-sync`, `split-whisper`, `word-audit`, …) and can be removed with `git worktree prune` once their PRs are merged.
