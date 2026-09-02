-- Move the internal language key to ISO 639-1 codes.
--
-- Before: `words.language`, `languagelevels.language` and every RPC argument
-- used English long names ('spanish'); `userdata`, both clients and parts of
-- the API used ISO codes ('es'). Ten ad-hoc conversion sites bridged the two,
-- two of them missing 'fr' entirely.
--
-- After: ISO codes everywhere. Long names are a display concern only.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector. This repo
-- carries no schema history and there is no Supabase CLI setup -- the deployed
-- database is the source of truth. This file is a runbook and a review
-- artifact, not something that will be picked up and run automatically. It
-- deliberately does not sit under supabase/migrations/, which would imply the
-- opposite and go stale the moment anyone edited the schema directly.
--
-- NOT YET APPLIED. Run against production only after taking a PITR
-- checkpoint -- section 1 is the one irreversible step. Deploy the API and
-- web changes and reload the extension immediately after; between the two,
-- clients send long names against an ISO column and get empty results (no
-- errors, no data loss, just blank lists).
--
-- Verified before writing this:
--   * mapping all four long names to ISO produces 0 duplicate (root, language)
--     pairs, so words_root_language_key survives untouched
--   * no views or materialized views exist in the schema

begin;

-- ---------------------------------------------------------------------------
-- 1. Data
-- ---------------------------------------------------------------------------

update public.words
   set language = case lower(trim(language))
         when 'spanish' then 'es'
         when 'german'  then 'de'
         when 'italian' then 'it'
         when 'french'  then 'fr'
       end
 where lower(trim(language)) in ('spanish', 'german', 'italian', 'french');

-- Deliberately untouched: 10 rows tagged 'MANUAL_TRANSLATION' and 2 whose
-- language column holds a YouTube video ID. None are referenced by userwords.
-- The video IDs point at an importer writing the wrong field; find it before
-- deleting the evidence.

-- languagelevels.language is a denormalised copy of words.language that has
-- drifted: 3785 rows (every German one) hold '' rather than a language. That
-- is why the /understanding-curve endpoint, which filters this table directly,
-- returns nothing for German. Backfill from words rather than mapping in
-- place, which fixes the empty rows in the same pass.
update public.languagelevels ll
   set language = w.language          -- already ISO from the statement above
  from public.words w
 where w.id = ll.word_id
   and ll.language is distinct from w.language;

update public.userdata
   set default_language = case lower(trim(default_language))
         when 'spanish' then 'es'
         when 'german'  then 'de'
         when 'italian' then 'it'
         when 'french'  then 'fr'
         else default_language
       end,
       -- distinct also collapses the one row holding ['spanish'] seven times
       languages = (
         select array_agg(distinct case lower(trim(l))
                 when 'spanish' then 'es'
                 when 'german'  then 'de'
                 when 'italian' then 'it'
                 when 'french'  then 'fr'
                 else l
               end)
           from unnest(languages) as l
       );

-- ---------------------------------------------------------------------------
-- 2. Functions
-- ---------------------------------------------------------------------------

-- The other 17 language-taking functions need no change: they compare their
-- argument against words.language, so once the column holds ISO codes they
-- simply mean ISO codes. get_random_words, which always took an ISO code and
-- compared it to a long name, becomes correct for free.
--
-- initialize_account is the exception -- it did the mapping itself.
create or replace function public.initialize_account(_language text, _language_level text)
 returns void
 language plpgsql
 set search_path to 'public', 'pg_temp'
as $function$
BEGIN
    IF _language NOT IN ('es', 'fr', 'de', 'it') THEN
        RAISE EXCEPTION
          'Unsupported language code: "%". Expected es, fr, de or it.',
          _language;
    END IF;

    INSERT INTO public.userwords
         (user_id, word_id, status, created_at, next_review_due_at)
    SELECT auth.uid(), ll.word_id, 'known', now(), NULL
      FROM public.languagelevels ll
      JOIN public.words w ON w.id = ll.word_id
     WHERE ll.language_level = _language_level
       AND w.language = _language
    ON CONFLICT (user_id, word_id) DO UPDATE
        SET status             = 'known',
            next_review_due_at = NULL;

    INSERT INTO public.userdata
            (user_id,     languages,        default_language)
    VALUES  (auth.uid(), ARRAY[_language],  _language)
    ON CONFLICT (user_id) DO UPDATE
        SET languages =
              CASE
                  WHEN NOT _language = ANY(userdata.languages)
                  THEN array_append(userdata.languages, _language)
                  ELSE userdata.languages
              END,
            default_language = _language;
END;
$function$;

-- ---------------------------------------------------------------------------
-- 3. Guard rails
-- ---------------------------------------------------------------------------

-- `not valid` so the check binds new writes immediately without a full-table
-- scan under lock. Validate once the 12 junk rows above have been dealt with:
--   alter table public.words validate constraint words_language_is_iso;
alter table public.words
  add constraint words_language_is_iso
  check (language in ('es', 'de', 'it', 'fr')) not valid;

alter table public.userdata
  add constraint userdata_default_language_is_iso
  check (default_language is null or default_language in ('es', 'de', 'it', 'fr')) not valid;

commit;
