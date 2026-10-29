-- Functions nothing calls (docs/plans/learner-word-data-model.md, step 4).
--
-- Each reads flashcardtests or the SM-2 columns on userwords, so every one
-- dropped here is one fewer to rewrite if Langfour becomes an SRS provider
-- (step 3). Checked 2026-10-29: no caller on origin/main anywhere in apps/
-- (web, API, extension, Safari, RemNote plugin), and no call in the Supabase
-- API logs, which only reach back 24 hours and held 24 requests. The web app
-- deploys from main, so only an old copy of the extension could still call
-- one, and the extension calls none of these on any branch.
--
-- The get_learning_words overloads dropped are the three the web app does not
-- call: it passes all six named arguments, which PostgREST resolves to the
-- (…, language_filter, source_filter) overload, kept.
--
-- HOW THIS GETS APPLIED: through the Supabase connector. Idempotent. Not
-- reversible from this file; the definitions are in the database's history
-- (pg_dump) and in git for the ones that were ever committed.

drop function if exists public.get_overdue_words(language_filter text, due_type text, page_size integer);
drop function if exists public.get_top_words_by_due_date();
drop function if exists public.get_user_words(language_filter text);
drop function if exists public.get_userwords_for_review(language_filter text);
drop function if exists public.get_user_words_with_cursor(last_fetched_id integer, fetch_limit integer);
drop function if exists public.get_user_words_with_tests(page_size integer, cursor_word_id integer);
drop function if exists public.get_user_words_with_tests(page_size integer, cursor_word_id integer, order_direction text, search_term text);
drop function if exists public.get_user_words_with_tests(page_size integer, cursor_word_id integer, order_direction text, search_term text, word_language text);
drop function if exists public.get_streak_data();
drop function if exists public.get_revision_counts_by_language(language_filter text);
drop function if exists public.words_known_by_date(language_filter text);
drop function if exists public.unique_learned(p_language text);
drop function if exists public.recall_efficiency_last_7_days();
drop function if exists public.get_learning_and_unknown_words(_word_ids integer[]);
drop function if exists public.get_learning_words(order_direction text, cursor_word_id integer, search_term text, page_size integer);
drop function if exists public.get_learning_words(order_direction text, cursor_word_id integer, search_term text, page_size integer, language_filter text);
drop function if exists public.get_learning_words(order_direction text, cursor_days_due integer, cursor_word_id integer, search_term text, page_size integer, language_filter text);
