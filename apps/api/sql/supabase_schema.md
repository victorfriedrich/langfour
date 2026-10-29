# Supabase schema inventory

Structure only, no data. Read from the hosted project on 2026-09-06, after
`drop_dictionary_audit_tables.sql` removed the nine audit tables, with the
read-only queries at the bottom; re-run them and replace this file when the
schema changes. The database is the source of truth, this file is the map.

Project: `xpovcmbrttmkhnrfspvo` (eu-central-1). Schema `public`.
RLS is enabled on every table. A table with no policies is reachable only
with the `service_role` key, i.e. only by the API.

## Tables

### Dictionary (shared, read by every signed-in user, written by the API and admins)

| Table | Columns | Keys and constraints |
|---|---|---|
| `words` | `id`, `root`, `language`, `translation`, `source`, `flagged`, `cognate` | PK `id`; unique `(root, language)`; `language` in `es, de, it, fr`; index on `root` |
| `wordforms` | `id`, `word_id`, `form`, `flagged` | PK `id`; FK `word_id → words`; unique `(word_id, form)`; index on `form` |
| `lexicon_pages` | `language`, `last_word_id`, `entries`, `built_at` | PK `(language, last_word_id)`; the valid dictionary as text pages, built by `rebuild_lexicon_pages` (lexicon.sql); authenticated read |
| `languagelevels` | `id`, `word_id`, `language`, `language_level` | PK `id`; FK `word_id → words`; unique `(word_id, language_level, language)`; level in `A1..C1` |

Policies on all three: `*_select_authenticated`, `*_insert_admin`,
`*_update_admin`, `*_delete_admin`. Admin is decided by `is_admin()`.

### Per-user state (each row belongs to `auth.uid()`)

| Table | Columns | Keys and constraints |
|---|---|---|
| `userdata` | `user_id`, `languages text[]`, `default_language`, `known_words_updated_at`, `review_provider` | PK `user_id`; FK → `auth.users`; `default_language` in the four codes; `review_provider` in `langfour, remnote`, default `langfour` |
| `userwords` | `id`, `user_id`, `word_id`, `status`, `source`, `created_at`, `last_reviewed_at`, `next_review_due_at`, `ease_factor`, `repetition`, `interval_days` | PK `id`; unique `(user_id, word_id)`; `status` in `learning, known, disabled` (`disabled`: flashcards turned off in RemNote, set by the sync; see `remnote_sync.sql`); SM-2 fields default `ease_factor 2.5`, `interval_days 1` |
| `flashcardtests` | `id`, `user_id`, `word_id`, `test_type`, `test_result`, `tested_at` | PK `id`; `test_type` in `flashcard, typing`; index `(user_id, word_id, test_result)` |
| `usertranslations` | `id`, `user_id`, `word_id`, `custom_translation`, `created_at` | PK `id`; index `(user_id, word_id)` |
| `videos_seen` | `id`, `user_id`, `video_id`, `seen_at` | PK `id` (identity); unique `(user_id, video_id)` |
| `user_roles` | `user_id`, `role`, `created_at` | PK `user_id`; `role` in `user, admin` |

Policies: `*_select_own`, `*_insert_own`, `*_update_own`, `*_delete_own` on
each, except `user_roles`, which has `select_own` only (roles are granted
with `service_role`).

### RemNote sync (`remnote_sync.sql`, applied 2026-09-26)

| Table | Columns | Keys and constraints |
|---|---|---|
| `srs_notes` | `id`, `user_id`, `word_id`, `provider`, `external_id`, `created_at`, `removed_at` | PK `id` (identity); FK `(user_id, word_id) → userwords` on delete cascade; unique `(user_id, provider, word_id)` and `(user_id, provider, external_id)`; `provider` in `remnote`, plus `langfour` once `langfour_provider.sql` is applied (then `external_id` is null for Langfour notes) |
| `srs_cards` | `id`, `note_id`, `external_id`, `kind`, `next_due_at` | PK `id` (identity); FK `note_id → srs_notes` on delete cascade; unique `(note_id, external_id)`; `kind` in `forward, backward, cloze`; index on `note_id` |
| `srs_reviews` | `card_id`, `reviewed_at`, `outcome` | PK `(card_id, reviewed_at)`; FK `card_id → srs_cards` on delete cascade; `outcome` in `again, hard, good, easy` |
| `api_tokens` | `id`, `user_id`, `purpose`, `token_hash`, `created_at`, `last_used_at`, `revoked_at` | PK `id`; unique `token_hash`; partial unique `(user_id, purpose) where revoked_at is null`; `purpose` in `remnote_sync` |
| `srs_sync_leases` | `user_id`, `holder`, `expires_at` | PK `user_id`; FK → `auth.users` |
| `api_token_pairings` | `id`, `purpose`, `secret_hash`, `user_code`, `user_id`, `approved_at`, `created_at`, `expires_at` | PK `id`; unique `secret_hash` and `user_code`; FK `user_id → auth.users`; `purpose` in `remnote_sync`. Applied as migration `remnote_token_pairings` |

Policies: `srs_*_select_own` on the three `srs_` data tables (cards and
reviews check ownership through `srs_notes`). `api_tokens`,
`api_token_pairings` and `srs_sync_leases` have none: only the API reads or
writes them.

### Word events and the practice outbox (`word_events.sql`, `srs_outbox.sql`, applied 2026-10-29)

| Table | Columns | Keys and constraints |
|---|---|---|
| `word_events` | `id`, `user_id`, `word_id`, `kind`, `source`, `occurred_at`, `context jsonb` | PK `id` (identity); FK `user_id → auth.users` on delete cascade, `word_id → words`; `kind` in `saved, lookup, exposure, recall_correct, recall_wrong`; `source` in `chatgpt, reader, video, extension, web`; indexes `(user_id, word_id)`, `(user_id, occurred_at)`. Append-only: policies `select_own`, `insert_own`, no update/delete for clients |
| `srs_outbox` | `event_id`, `card_id`, `outcome`, `status`, `decided_at`, `reason`, `applied_review_at` | PK `event_id` → `word_events` on delete cascade; FK `card_id → srs_cards` on delete set null; `outcome` in `again, good`; `status` in `pending, applied, skipped`; partial index `(card_id) where status = 'pending'`. Policy `select_own` through `word_events`; written only by the API |

### Langfour as a provider (`langfour_provider.sql`, not applied yet)

Langfour's schedule moves from the SM-2 columns on `userwords` into the
`srs_*` tables as provider `langfour`: a note and one `forward` card per
learning word (a trigger on `userwords` creates them), its reviews in
`srs_reviews`. New table `srs_card_sm2` (`card_id` PK → `srs_cards`,
`ease_factor`, `repetition`, `interval_days`; policy `select_own`). New
functions, service role only: `srs_langfour_card`, `srs_langfour_review`
(the API's practice path), `srs_carry_over_due` (on disconnecting RemNote).
The SM-2 columns and `flashcardtests` stay, unread, until they are dropped.

Also `userdata.remnote_last_sync_at` (end of `remnote_sync.sql`): when the
plugin last completed a sync run. See `docs/plans/learner-word-data-model.md`.

### Known words (`known_words.sql`, applied 2026-10-01)

`user_known_words` is a view (`security_invoker`, so RLS applies): one row
per known word with `source` `declared` (userwords.status = 'known') or
`reviews` (learned in Langfour's or RemNote's reviews; rule mirrors
`apps/remnote-plugin/src/stats.ts`). Read by the recommender and the
Vocabulary page; see the functions `known_words_summary` and
`get_known_words_page` below.

### Ingestion

| Table | Columns | Keys and constraints |
|---|---|---|
| `video_queue` | `video_id`, `lang`, `channel_id`, `title`, `duration_s`, `views`, `score`, `source`, `priority`, `status`, `attempts`, `error`, `submitted_by`, `created_at`, `claimed_at`, `done_at` | PK `video_id`; FK `submitted_by → auth.users`; `source` in `discovery, user, manual, legacy`; `status` in `pending, processing, done, failed, skipped`; partial index `(lang, priority desc, score desc) where status = 'pending'`, which is exactly `ingest.py`'s claim query; index on `channel_id` |
| `pending_words` | `language`, `word`, `outcome`, `source`, `candidates text[]`, `jev jsonb`, `seen`, `created_at`, `resolved_at` | PK `(language, word)`; `outcome` in `pending, not_a_word`. Unknown tokens `parse()` did not attach to a root; written through `record_pending_words(rows jsonb)` (service role only) |

Policies: `users queue own videos [insert]`, `users read own submissions
[select]`. Workers claim and update rows with `service_role`. Definition in
`video_queue.sql`. `pending_words` (`pending_words.sql`, applied 2026-10-15) has RLS on
and no policies: only `service_role` reads or writes it.

## Functions

All are `SECURITY INVOKER` except `is_admin()`, so they run under the caller's
RLS. Every function filters on `auth.uid()` internally; none takes a user id
as a parameter any more. The `caller` column is from a grep for the literal
name in each app; `none` means nothing in the repo calls it today.

| Function | Returns | Caller |
|---|---|---|
| `add_custom_translation(_word_id int, _custom_translation text)` | void | web |
| `get_available_languages()` | text[] | web, extension |
| `get_known_words(user_id text, include_cognates bool)` | table(word_id) | extension |
| `get_known_words(_target_language text, _limit int, _offset int)` | table(word, total_count) | none |
| `get_known_words_update_timestamp()` | timestamp | extension |
| `get_learning_words(…, language_filter, source_filter)` | same + `source` | web |
| `get_random_words(language_code, limit_words)` | table(id, root) | api |
| `get_seen_video_ids()` | table(video_id) | web |
| `get_translation_for_word(_word_id)` | text | web |
| `get_user_counts_with_wordforms(_word_id)` | table(reviewcount, seencount, alternative_wordforms) | web. Reviews from `srs_reviews` (live notes, any provider), exposures from `word_events` |
| `get_user_default_language()` | text | web, extension |
| `get_userword_sources()` | table(source) | web |
| `get_userwords_filtered(language_filter, due_type, page_size, p_source)` | table(word_id, word_root, translation, next_review_due_at) | web |
| `get_words_by_ids(word_ids int[])` | table(word_id, word, translation) | web |
| `get_words_with_many_forms()` | table(id, root) | api |
| `get_words_with_wordforms_cursor(language_param, last_fetched_word_id, fetch_limit)` | table(word_id, word, wordform) | api, loads the word cache at boot |
| `get_known_words_page(language_filter, search_term, cursor_word_id, page_size)` | table(word_id, word, translation, source) | web. Reads `user_known_words` |
| `initialize_account(_language_level varchar)` | void | web |
| `initialize_account(_language text, _language_level text)` | void | web |
| `insert_flashcard_test(_word_id, _test_type, _test_result)` | void | web; no longer called once `langfour_provider.sql` is applied (update_spaced_repetition records the review) |
| `is_admin()` | boolean | RLS policies. `SECURITY DEFINER`, reads `user_roles` |
| `load_unseen_words()` | table(word_id, root, translation) | web |
| `known_words_summary(language_filter)` | table(declared, from_reviews) | web. Reads `user_known_words` |
| `lexicon_page(language_filter, after_word_id, page_words)` | table(last_word_id, entries text) | extension. Reads `lexicon_pages` (lexicon.sql) |
| `mark_video_as_seen(input_video_id)` | void | web |
| `move_words_to_userwords(_word_ids int[])` | void | extension |
| `move_words_to_userwords(_word_ids int[], _status, _source)` | void | none |
| `my_word_statuses()` | jsonb [[word_id, status]] | extension. Reads `userwords`, `user_known_words` (lexicon.sql) |
| `rebuild_lexicon_pages(language_filter, page_words)` | integer | run by hand after dictionary changes; not granted to clients (lexicon.sql) |
| `set_user_default_language(_language)` | void | web, extension |
| `srs_acquire_sync_lease(p_user_id uuid, p_holder text, p_seconds int)` | boolean | api. Execute granted to `service_role` only; takes a user id for that reason |
| `set_userwords_status(_word_ids int[], _status)` | void | web |
| `total_words_known()` | integer | web |
| `total_words_known(language_filter)` | integer | web |
| `update_spaced_repetition(_word_id, _test_result)` | void | web. The SM-2 update lives here, not in client code. `langfour_provider.sql` (not applied yet) makes it record the review too and work on the word's Langfour card |

`unaccent`, `unaccent_init`, `unaccent_lexize` are the `unaccent` extension,
installed into `public`.

The API also reads and writes tables directly with `service_role`:
`words`, `wordforms`, `userwords`, `videos_seen`, `languagelevels`,
`video_queue`. The clients read `words`, `wordforms` and `userwords` directly
under RLS.

## Regenerating this file

Run these in the SQL editor or through the MCP connector. All three are
read-only.

```sql
-- functions
select p.proname, pg_get_function_identity_arguments(p.oid) as args,
       pg_get_function_result(p.oid) as returns,
       case when p.prosecdef then 'definer' else 'invoker' end as security,
       l.lanname as language
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
join pg_language l on l.oid = p.prolang
where n.nspname = 'public'
order by p.proname, args;

-- tables, RLS and policies
select c.relname, c.relrowsecurity,
       (select string_agg(pol.polname, ', ' order by pol.polname)
          from pg_policy pol where pol.polrelid = c.oid) as policies
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;

-- indexes
select tablename, indexname, indexdef
from pg_indexes where schemaname = 'public'
order by tablename, indexname;
```

Callers: grep each app for `.rpc('<name>'`.
