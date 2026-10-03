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
| `userwordinteraction` | `id`, `user_id`, `word_id`, `location`, `seen_at` | PK `id`. Never written to; read only by `get_user_counts_with_wordforms` |
| `videos_seen` | `id`, `user_id`, `video_id`, `seen_at` | PK `id` (identity); unique `(user_id, video_id)` |
| `user_roles` | `user_id`, `role`, `created_at` | PK `user_id`; `role` in `user, admin` |

Policies: `*_select_own`, `*_insert_own`, `*_update_own`, `*_delete_own` on
each, except `user_roles`, which has `select_own` only (roles are granted
with `service_role`).

### RemNote sync (`remnote_sync.sql`, applied 2026-09-26)

| Table | Columns | Keys and constraints |
|---|---|---|
| `srs_notes` | `id`, `user_id`, `word_id`, `provider`, `external_id`, `created_at`, `removed_at` | PK `id` (identity); FK `(user_id, word_id) → userwords` on delete cascade; unique `(user_id, provider, word_id)` and `(user_id, provider, external_id)`; `provider` in `remnote` |
| `srs_cards` | `id`, `note_id`, `external_id`, `kind`, `next_due_at` | PK `id` (identity); FK `note_id → srs_notes` on delete cascade; unique `(note_id, external_id)`; `kind` in `forward, backward, cloze`; index on `note_id` |
| `srs_reviews` | `card_id`, `reviewed_at`, `outcome` | PK `(card_id, reviewed_at)`; FK `card_id → srs_cards` on delete cascade; `outcome` in `again, hard, good, easy` |
| `api_tokens` | `id`, `user_id`, `purpose`, `token_hash`, `created_at`, `last_used_at`, `revoked_at` | PK `id`; unique `token_hash`; partial unique `(user_id, purpose) where revoked_at is null`; `purpose` in `remnote_sync` |
| `srs_sync_leases` | `user_id`, `holder`, `expires_at` | PK `user_id`; FK → `auth.users` |
| `api_token_pairings` | `id`, `purpose`, `secret_hash`, `user_code`, `user_id`, `approved_at`, `created_at`, `expires_at` | PK `id`; unique `secret_hash` and `user_code`; FK `user_id → auth.users`; `purpose` in `remnote_sync`. Applied as migration `remnote_token_pairings` |

Policies: `srs_*_select_own` on the three `srs_` data tables (cards and
reviews check ownership through `srs_notes`). `api_tokens`,
`api_token_pairings` and `srs_sync_leases` have none: only the API reads or
writes them.

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

Policies: `users queue own videos [insert]`, `users read own submissions
[select]`. Workers claim and update rows with `service_role`. Definition in
`video_queue.sql`.

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
| `get_learning_and_unknown_words(_word_ids int[])` | table(word_id, status) | none |
| `get_learning_words(order_direction, cursor_word_id, search_term, page_size)` | table(word_id, word, translation, status, review_due) | web |
| `get_learning_words(…, language_filter)` | same | web |
| `get_learning_words(…, language_filter, source_filter)` | same + `source` | web |
| `get_learning_words(order_direction, cursor_days_due, cursor_word_id, search_term, page_size, language_filter)` | same | web |
| `get_overdue_words(language_filter, due_type, page_size)` | table(word_id, word_root, translation, next_review_due_at) | none |
| `get_random_words(language_code, limit_words)` | table(id, root) | api |
| `get_revision_counts_by_language(language_filter)` | table(revision_date, revision_count) | web |
| `get_seen_video_ids()` | table(video_id) | web |
| `get_streak_data()` | table(revision_date, revision_count) | none |
| `get_top_words_by_due_date()` | table(word_id, word_root, translation, next_review_due_at) | none |
| `get_translation_for_word(_word_id)` | text | web |
| `get_user_counts_with_wordforms(_word_id)` | table(reviewcount, seencount, alternative_wordforms) | web |
| `get_user_default_language()` | text | web, extension |
| `get_user_words(language_filter)` | table(word_id, word_root, translation, next_review_due_at) | web |
| `get_user_words_with_cursor(last_fetched_id, fetch_limit)` | table(word, translation, status) | none |
| `get_user_words_with_tests(page_size, cursor_word_id)` | table(word_id, word, translation, status) | web |
| `get_user_words_with_tests(…, order_direction, search_term)` | same | web |
| `get_user_words_with_tests(…, order_direction, search_term, word_language)` | same | web |
| `get_userword_sources()` | table(source) | web |
| `get_userwords_filtered(language_filter, due_type, page_size, p_source)` | table(word_id, word_root, translation, next_review_due_at) | web |
| `get_userwords_for_review(language_filter)` | table(word_id, root, translation, next_review_due_at) | none |
| `get_words_by_ids(word_ids int[])` | table(word_id, word, translation) | web |
| `get_words_with_many_forms()` | table(id, root) | api |
| `get_words_with_wordforms_cursor(language_param, last_fetched_word_id, fetch_limit)` | table(word_id, word, wordform) | api, loads the word cache at boot |
| `get_known_words_page(language_filter, search_term, cursor_word_id, page_size)` | table(word_id, word, translation, source) | web. Reads `user_known_words` |
| `initialize_account(_language_level varchar)` | void | web |
| `initialize_account(_language text, _language_level text)` | void | web |
| `insert_flashcard_test(_word_id, _test_type, _test_result)` | void | web |
| `is_admin()` | boolean | RLS policies. `SECURITY DEFINER`, reads `user_roles` |
| `load_unseen_words()` | table(word_id, root, translation) | web |
| `known_words_summary(language_filter)` | table(declared, from_reviews) | web. Reads `user_known_words` |
| `mark_video_as_seen(input_video_id)` | void | web |
| `move_words_to_userwords(_word_ids int[])` | void | extension |
| `move_words_to_userwords(_word_ids int[], _status, _source)` | void | none |
| `recall_efficiency_last_7_days()` | numeric | web |
| `set_user_default_language(_language)` | void | web, extension |
| `srs_acquire_sync_lease(p_user_id uuid, p_holder text, p_seconds int)` | boolean | api. Execute granted to `service_role` only; takes a user id for that reason |
| `set_userwords_status(_word_ids int[], _status)` | void | web |
| `total_words_known()` | integer | web |
| `total_words_known(language_filter)` | integer | web |
| `unique_learned(p_language)` | integer | web |
| `update_spaced_repetition(_word_id, _test_result)` | void | web. The SM-2 update lives here, not in client code |
| `words_known_by_date(language_filter)` | table(date, words_known) | web |

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
