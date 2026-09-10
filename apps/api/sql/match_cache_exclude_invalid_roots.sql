-- Exclude known-bad roots from the word match cache.
--
-- get_words_with_wordforms_cursor() feeds database.initialize_cache(), which
-- builds the two dicts every token is resolved against. It filtered
-- wordforms.flagged but nothing on the words side, so a root marked
-- cognate='invalid' -- wrong-language ("the horse", "el id"), proper nouns
-- ("el cuasimodo"), typos ("pgmento") -- stayed a live target for both
-- transcript matching and identify_word_id()'s wordform resolution.
--
-- That is how the surface form "hecha" came to be written against word 199369,
-- whose root is the English gloss "the fact": five roots claim the form
-- "hecho" (hacer, el hecho, el fact, hace, the fact) and the loader handed it
-- to the highest id. The Python side now uses setdefault so the most
-- established root keeps a homograph; this removes the invalid claimants
-- entirely.
--
-- IS DISTINCT FROM, not <>: cognate is NULL for 132,447 of 179,381 rows, and
-- `cognate <> 'invalid'` evaluates to NULL for those, which would empty the
-- cache and trip initialize_cache()'s refuse-to-serve guard.

CREATE OR REPLACE FUNCTION public.get_words_with_wordforms_cursor(
  language_param text,
  last_fetched_word_id integer DEFAULT NULL::integer,
  fetch_limit integer DEFAULT 10)
 RETURNS TABLE(word_id integer, word text, wordform text)
 LANGUAGE plpgsql
 SET search_path TO 'public', 'pg_temp'
AS $function$
BEGIN
  RETURN QUERY
  WITH selected_words AS (
    SELECT
      w.id AS word_id,
      w.root AS word
    FROM words w
    WHERE w.language = language_param
      AND (last_fetched_word_id IS NULL OR w.id > last_fetched_word_id)
      AND w.cognate IS DISTINCT FROM 'invalid'   -- exclude known-bad roots
    ORDER BY w.id ASC
    LIMIT fetch_limit
  )
  SELECT
    sw.word_id,
    sw.word,
    wf.form AS wordform
  FROM selected_words sw
  LEFT JOIN wordforms wf
    ON sw.word_id = wf.word_id
    AND (wf.flagged IS NULL OR wf.flagged = false)  -- exclude known-bad forms
  ORDER BY sw.word_id ASC;
END;
$function$;
