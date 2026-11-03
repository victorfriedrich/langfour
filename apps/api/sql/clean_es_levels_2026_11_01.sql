-- Spanish onboarding levels: take out what is clearly wrong, nothing else.
--
-- The levels (languagelevels, read by initialize_account at sign-up) are the
-- first 700 / 1,400 / 2,200 / 5,000 entries of the CREA frequency list. They
-- predate the word review, so they still list entries the review marked
-- invalid: 46 in A1, 128 in A2, 271 in B1, 959 in B2 (forms like "ha" and
-- "gran", names, places, English, abbreviations). New accounts get those as
-- known words. The CREA order and the level sizes otherwise stay as they are.
--
-- 1. Archive today's es rows, so the change can be undone.
-- 2. Delete the invalid entries.
-- 3. Where an invalid entry was clearly a form of a real word that the level
--    doesn't already have, add that word, at the entry's level and above.
--    Checked by hand (2026-11-01) against the 132 entries whose form matches
--    a valid word. Most of those words are already in the level (ha -> haber,
--    gran -> grande), so nothing is added for them. Wrong matches are only
--    dropped: espana -> el espanol, argentina -> argentino, sanchez ->
--    el sancho, corea -> corear, suiza, florida, polonia, mercedes, sofia,
--    logan, cesar, andalucia, agustin, cia. So are unclear ones: ex, cristo,
--    debate, tina, serena, id, can, tara.
--
-- Ids follow the CREA order only for the original entries: the added words
-- get new ids, after every original one. Membership is unaffected, which is
-- all initialize_account and scripts/judge_thumbnails.py read. The one reader
-- that takes "the first N by id" as the most frequent words is app.py's
-- /recommendations/words/chart-data, which nothing calls.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector or the SQL
-- editor, in one transaction. APPLIED 2026-11-03: the check below gave the
-- expected counts, with 9,310 rows archived. Undo:
--   delete from public.languagelevels where language = 'es';
--   insert into public.languagelevels select * from archive.languagelevels_es_2026_11_01;

begin;

create schema if not exists archive;
create table archive.languagelevels_es_2026_11_01 as
  select * from public.languagelevels where language = 'es';

delete from public.languagelevels ll
using public.words w
where w.id = ll.word_id and ll.language = 'es' and w.status = 'invalid';

with add(word_id, from_level) as (values
  -- A1: ninguna/ningun -> ninguno, os, plan -> el plan, control -> el control, carne -> la carne
  (102109, 'A1'), (210822, 'A1'), (198977, 'A1'), (112090, 'A1'), (135968, 'A1'),
  -- A2: red -> la red, fe -> la fe
  (104754, 'A2'), (110516, 'A2'),
  -- B1: produce -> producir, primo -> el primo, mono -> el mono, meta -> la meta
  (103693, 'B1'), (106294, 'B1'), (105299, 'B1'), (103763, 'B1'),
  -- B2: tele, combustible, manual, coincide, eco, surge, shock, test, documental,
  --     polla, coco, atlantico, retrocede, entere, vaticano, bate
  (128580, 'B2'), (200222, 'B2'), (193834, 'B2'), (109264, 'B2'), (111601, 'B2'),
  (107004, 'B2'), (136227, 'B2'), (139671, 'B2'), (157376, 'B2'), (114202, 'B2'),
  (113684, 'B2'), (210855, 'B2'), (106866, 'B2'), (106813, 'B2'), (196697, 'B2'), (108987, 'B2')
), lv(level) as (values ('A1'), ('A2'), ('B1'), ('B2'))
insert into public.languagelevels (word_id, language_level, language, created_at)
select a.word_id, lv.level, 'es', now()
from add a
join lv on lv.level >= a.from_level
join public.words w on w.id = a.word_id and w.status = 'valid' and w.language = 'es'
on conflict (word_id, language_level, language) do nothing;

commit;

-- Check afterwards (expected: no invalid entries; A1 662, A2 1,281, B1 1,941, B2 4,064):
-- select ll.language_level, count(*) as words,
--        count(*) filter (where w.status is distinct from 'valid') as not_valid
-- from public.languagelevels ll join public.words w on w.id = ll.word_id
-- where ll.language = 'es' group by 1 order by 1;
