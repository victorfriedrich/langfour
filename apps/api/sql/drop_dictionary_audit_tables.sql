-- Drop the working tables of the August 2026 dictionary audit.
--
-- The audit checked words/wordforms against Wiktionary lemma data from
-- kaikki.org, wrote its verdicts into word_invalid_audit, and archived the
-- wordforms it removed. It finished on 2026-08-18; the corrections are in
-- words/wordforms, and nothing has read these tables since. No function,
-- policy, view, trigger or client references them (checked against pg_proc,
-- pg_policy, pg_depend and a repo-wide grep before applying).
--
-- wordforms_duplicate is a pre-audit copy of wordforms with a foreign key
-- to words; the key goes with the table.
--
-- Applied by hand through the Supabase connector on 2026-09-06, like the other
-- files in this directory. Idempotent.

drop table if exists public.kaikki_lemmas_stage;
drop table if exists public.kaikki_form_lemma_stage;
drop table if exists public.kaikki_check_stage;
drop table if exists public.kaikki_wordform_mismatch_stage;
drop table if exists public.kaikki_wordform_check_v2;
drop table if exists public.kaikki_job_status;
drop table if exists public.word_invalid_audit;
drop table if exists public.wordforms_removed_archive;
drop table if exists public.wordforms_duplicate;
