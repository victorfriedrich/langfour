-- como, vale and gracias for the learners who already know them.
--
-- Until 2026-10-05 the dictionary had no root for these three, so every
-- "como" in a transcript counted as comer, "vale" as el vale (voucher) and
-- "gracias" as la gracia. The word review added the missing roots (210840,
-- 210841, 210842) and relinked the transcripts to them. The onboarding levels
-- and the 150-odd learners who took one still have only the old roots, so
-- como, vale and gracias count as new words for them in every video.
--
-- The old roots are real words (to eat, voucher, grace), so their rows stay.
-- Each user who knows an old root also gets the new one as known, unless
-- they already have it in any status. Learning rows are not copied: learning
-- "comer" says nothing about "como". The rows carry their own source, so
-- they can be told apart and undone:
--   delete from public.userwords where source = 'reroot_2026-10-05';
-- Known rows don't fire the userwords trigger (it only makes cards for
-- learning words), so nothing is created in srs_notes or RemNote.
--
-- The onboarding levels (languagelevels, read by initialize_account) get the
-- new roots wherever they list the old ones.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector, like the
-- other files here. Idempotent: safe to re-run.

with reroot(old_id, new_id) as (
    values (101412, 210840),  -- comer     -> como
           (101542, 210841),  -- el vale   -> vale
           (101450, 210842)   -- la gracia -> gracias
)
insert into public.userwords (user_id, word_id, status, created_at, source)
select uw.user_id, r.new_id, 'known', now(), 'reroot_2026-10-05'
from reroot r
join public.userwords uw on uw.word_id = r.old_id and uw.status = 'known'
where uw.user_id is not null
on conflict (user_id, word_id) do nothing;

with reroot(old_id, new_id) as (
    values (101412, 210840), (101542, 210841), (101450, 210842)
)
insert into public.languagelevels (word_id, language_level, language)
select r.new_id, ll.language_level, ll.language
from reroot r
join public.languagelevels ll on ll.word_id = r.old_id
on conflict (word_id, language_level, language) do nothing;

-- Read-only counts, before and after (2026-11-01, before: 459 userwords rows
-- and 12 languagelevels rows to add).
--
-- with reroot(old_id, new_id) as (
--     values (101412, 210840), (101542, 210841), (101450, 210842)
-- )
-- select r.old_id, r.new_id,
--        count(*) filter (where uw.status = 'known') as known_old,
--        count(*) filter (where uw.status = 'known' and not exists (
--            select 1 from public.userwords d
--            where d.user_id = uw.user_id and d.word_id = r.new_id)) as to_add
-- from reroot r join public.userwords uw on uw.word_id = r.old_id
-- group by 1, 2;
