-- Classify the words of a text for the signed-in user.
--
-- The article reader (apps/extension/src/reader.ts) used to decide what to
-- highlight by comparing each word's spelling with the user's known-words
-- list. Anything not on the list counted as new: names (Trump, Puigdemont),
-- acronyms (EFE, GPS), fragments (the K of 4K). The dictionary already says
-- which of those are vocabulary -- the audit marks them words.status =
-- 'invalid' -- and user_known_words already says what "known" means, so
-- this function only puts the two together.
--
-- For each distinct token: the valid dictionary word it belongs to, and the
-- user's relation to that word. Tokens that are not vocabulary are left out
-- of the result, so the caller treats "no row" as "not a word to learn".
--
--   status 'known'    in user_known_words (declared, or proven in reviews)
--          'learning' in userwords, still being practised
--          'ignored'  in userwords as 'disabled' (cards turned off in RemNote)
--          'new'      not in userwords at all
--
-- Matching follows identify_word_id in apps/api/database.py: roots and word
-- forms both count, root first when everything else is equal. Tokens are tried as written and lowercased, which keeps
-- the btree indexes on words.root and wordforms.form usable: forms are stored
-- lowercase except German nouns.
--
-- HOW THIS GETS APPLIED: through the Supabase connector, like the other
-- files here. Idempotent.

create or replace function public.classify_words(language_filter text, tokens text[])
returns table (token text, word_id integer, status text)
language sql
stable
security invoker
set search_path = ''
as $$
    with input as (
        select distinct t as token
        from unnest(tokens) as t
        where t is not null and length(t) between 1 and 64
    ),
    candidates as (
        select i.token, m.word_id, m.priority
        from input i
        cross join lateral (
            select w.id as word_id, 1 as priority
            from public.words w
            where w.root in (i.token, lower(i.token))
              and w.language = language_filter
              and w.status = 'valid'
            union all
            select wf.word_id, 2
            from public.wordforms wf
            join public.words w on w.id = wf.word_id
            where wf.form in (i.token, lower(i.token))
              -- Audit status supersedes the legacy flagged column.
              and wf.status = 'valid'
              and w.language = language_filter
              and w.status = 'valid'
        ) m
    ),
    known as (
        select k.word_id
        from public.user_known_words k
        where k.user_id = (select auth.uid())
          and k.word_id in (select word_id from candidates)
    ),
    mine as (
        select uw.word_id, uw.status
        from public.userwords uw
        where uw.user_id = (select auth.uid())
          and uw.word_id in (select word_id from candidates)
    ),
    rated as (
        select c.token, c.word_id, c.priority,
               case
                   when c.word_id in (select word_id from known) then 'known'
                   when u.status = 'disabled' then 'ignored'
                   when u.status is not null then 'learning'
                   else 'new'
               end as status
        from candidates c
        left join mine u on u.word_id = c.word_id
    )
    -- One row per token. A spelling can belong to several words ("como":
    -- como and comer); it is only new if none of them is known, so the
    -- user's best relation wins, then root over word form.
    select distinct on (r.token) r.token, r.word_id, r.status
    from rated r
    order by r.token,
             case r.status when 'known' then 1 when 'ignored' then 2 when 'learning' then 3 else 4 end,
             r.priority,
             r.word_id;
$$;

grant execute on function public.classify_words(text, text[]) to authenticated;
