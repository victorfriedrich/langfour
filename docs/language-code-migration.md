# Migration: one internal language key (ISO 639-1)

Status: code landed 2026-09-01; **the data migration has not been run**. The SQL
lives in `docs/language-iso-migration.sql` and needs a PITR checkpoint before it
is applied.

Schema changes go through the Supabase connector by hand — this repo carries no
schema history and has no Supabase CLI setup, so the deployed database is the
source of truth. The SQL file is a runbook, not a migration anything runs
automatically; that is why it sits in `docs/` rather than `supabase/migrations/`.

## Goal

One internal key — the ISO 639-1 code (`es`, `de`, `it`, `fr`) — in the database, in every
RPC argument, in both clients, and in the API. Long names (`spanish`) become a *display*
concern only, produced from a single lookup table.

Today two vocabularies coexist and the boundary is drawn ad hoc in ten places, two of
which are missing `fr` entirely.

Single-operator project, so this is a straight cutover: change everything, accept a few
minutes of breakage, reload the extension. No expand/contract phasing, no bilingual
transition period.

## Why bother

- `determineLanguage` (`apps/extension/src/contentScript.ts:32`) has no `'fr'` case and
  falls through to `default: 'spanish'` — a French learner gets Spanish known-words.
- `apps/api/app.py:401` also omits `'fr'`, so `'fr'` reaches a `words.language = 'fr'`
  comparison and the missing-words endpoint returns nothing for French.
- `get_random_words(language_code)` takes an ISO code and compares it to long names.
  Broken for every language, today.
- 23 `userdata` rows hold long names where `initialize_account` writes ISO codes. The
  extension popup renders those as ISO codes → broken flags and lowercase names. Clicking
  a language button writes the long name back, so it is self-sustaining.
- Three "supported languages" lists disagree: web `es/de/it/fr` (`UserContext.tsx:51`),
  `apps/api/database.py:17` `spanish/french/german` (no Italian, despite 36k Italian
  words), content script `es/it/de` (no French).

## Measured state (2026-09-01, project `xpovcmbrttmkhnrfspvo`)

**Long names:** `words.language` (`spanish` 73204, `italian` 35954, `french` 35925,
`german` 34256, plus junk: `MANUAL_TRANSLATION` 10, `Italian` 2, `jx2R84gaOeE` 1,
`EdXU1r7f6JY` 1); `languagelevels.language`; every RPC language argument;
`instructionmanager.py`; `database.py`.

**ISO codes:** `userdata.languages`/`default_language` (`es` 117, `de` 2, `it` 2 — plus
`spanish` 23, `french` 1); web `LanguageOption.code`; `localStorage['selected-language']`;
`chrome.storage.sync.preferredLanguage`; `get_random_words`.

**Scale:** 145 `userdata` rows, 203 accounts with words, but 10 active in 90 days and
3 running tests. Effectively dormant.

### Things that make this safe

- **No views or materialized views exist.** Nothing to recreate.
- **Zero collisions.** Mapping all four long names to ISO produces 0 duplicate
  `(root, language)` pairs, so `words_root_language_key UNIQUE (root, language)` survives
  untouched. Verified by query.
- **`languagelevels.language` is nearly dead, but not quite.** `initialize_account` filters
  on `w.language`, not `ll.language`. No RPC reads it. But `app.py` queries the table
  directly over PostgREST for the understanding-curve endpoint, filtering on this column —
  which is why that endpoint returns nothing for German, whose 3785 rows hold `''`. The
  migration backfills the column from `words` rather than mapping it in place, fixing both.

### Separate pre-existing bugs — do not bundle

- **French has no `languagelevels` rows at all**, so `initialize_account('fr', …)` seeds
  zero known words. This migration will not fix it; it needs level data.
- `words.language = 'Italian'` is 2 words held by 18 users (36 `userwords` rows),
  invisible to every `language = 'italian'` query today. Normalising case makes them
  appear.

## The migration

### Step 1 — data

Take a PITR checkpoint first. This is the only irreversible step.

```sql
begin;

update public.words
   set language = case lower(trim(language))
     when 'spanish' then 'es' when 'german' then 'de'
     when 'italian' then 'it' when 'french' then 'fr'
   end
 where lower(trim(language)) in ('spanish','german','italian','french');

update public.userdata
   set default_language = case lower(trim(default_language))
         when 'spanish' then 'es' when 'german' then 'de'
         when 'italian' then 'it' when 'french' then 'fr'
         else default_language end,
       languages = (
         select array_agg(distinct case lower(trim(l))
                 when 'spanish' then 'es' when 'german' then 'de'
                 when 'italian' then 'it' when 'french' then 'fr'
                 else l end)
         from unnest(languages) as l
       );

commit;
```

`array_agg(distinct …)` also de-duplicates the `['spanish' × 7]` row.

Leaves alone: the 12 junk `words` rows (`MANUAL_TRANSLATION`, and two rows whose language
column contains a YouTube video ID — worth finding that writer before deleting the
evidence) and `languagelevels.language` (dead; drop the column separately if you like).

### Step 2 — RPCs

The 18 language-taking functions compare their argument against `words.language`. Once the
column holds ISO codes they need **no signature change and no body change** — they just
start meaning ISO. Only rename parameters for clarity if you want; that forces a
`drop function` + recreate because names are part of the identity for named-argument calls,
and PostgREST calls them by name. Not worth it.

Two exceptions that do need editing:

- `initialize_account` — delete the `CASE lower(_language)` block that maps to `lang_name`
  and the `RAISE EXCEPTION`; filter `w.language = _language` directly.
- `get_random_words` — no change needed; it becomes correct for free.

### Step 3 — clients

One shared module per app, replacing ten ad-hoc conversion sites:

- `apps/api/languages.py` — promote `media_import.normalize_language` here. Delete the
  dicts at `app.py:401`, `app.py:577`, `flashcards.py:273`, `flashcards.py:314`,
  `flashcards.py:371`, and the reverse map at `reparse.py:44`. Reconcile
  `database.py:17 SUPPORTED_LANGUAGES` with the web list (Italian is missing).
- `apps/web/src/lib/languages.ts` — `{ code, englishName, flag }`. Replace
  `language.name.toLowerCase()` with `language.code` in all eight hooks:
  `LearningWordsTable.tsx:222`, `useUserWords.ts:57`, `useFetchTotalWordsKnown.ts:17`,
  `useTopWords.ts:39`, `useStreakData.ts:31`, `useUniqueLearned.ts:19`,
  `useOverdueWords.ts:59`, `useWordsKnownByDate.ts:32`.
- `apps/extension/src/languages.ts` — delete `determineLanguage`
  (`contentScript.ts:32`) and pass `prefs.preferredLanguage` straight through. Replace
  `preferencePopup/languages.ts` (95 entries, exists only to type `Language`, lets `mhr`
  typecheck). Fix the popup to take flag and display name from the module rather than
  `flagcdn.com/${lang}.svg` + `Intl.DisplayNames` — the latter silently echoes its input
  for unknown tags, which is why the bug rendered as lowercase `spanish` instead of
  throwing.

Clear `chrome.storage.sync.preferredLanguage` and `localStorage['selected-language']` once
after deploying, in case either holds a stale long name.

### Step 4 — lock it in

```sql
alter table public.words
  add constraint words_language_is_iso
  check (language in ('es','de','it','fr')) not valid;
```

`not valid` so it applies to new writes without a full-table scan; `validate` it after
deciding what to do with the 12 junk rows. Same for `userdata.default_language`.

## Order and blast radius

DB first, then API and web deploy, then reload the extension. Between step 1 and step 3 the
clients send long names against an ISO column and return empty results — no data loss,
no errors, just blank lists. With 10 active accounts and no Web Store update to wait on,
that window is worth accepting.

## Open decisions

1. The 12 junk `words` rows — delete, or trace the importer first.
2. `languagelevels.language` — drop the column or backfill it.
3. Whether to fix the missing French `languagelevels` data in the same sitting.
