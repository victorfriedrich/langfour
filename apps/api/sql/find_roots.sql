-- find_roots: case-insensitive root lookup, many roots per call.
--
-- parse() falls back to the database for every token the word cache misses,
-- in case another worker added the root after the cache loaded. That lookup was
-- `root ILIKE <token>` through PostgREST, one request per token: no index can
-- serve ILIKE, so each scanned all ~180k words (224 ms in the database, ~350 ms
-- end to end), and a transcript with 27 misses spent 9 s on it. PostgREST can't
-- filter on lower(root), so the lookup is a function over an expression index.
--
-- HOW THIS GETS APPLIED: by hand, through the Supabase connector. The index is
-- built CONCURRENTLY so writes to words are never blocked; that statement can't
-- run inside a transaction, so run it on its own, before the function.
-- Idempotent.

create index concurrently if not exists words_language_lower_root_idx
    on public.words (language, lower(root));

-- Every root matching one of `roots` (any case), invalid ones included: the add
-- path must see audit rejections too. Lowest id first, as the cache orders them.
create or replace function public.find_roots(language_param text, roots text[])
returns table(id integer, root text, status text)
language sql
stable
security invoker
set search_path = ''
as $$
  select w.id, w.root, w.status
  from public.words w
  where w.language = language_param
    and lower(w.root) = any (select lower(r) from unnest(roots) r)
  order by w.id;
$$;

revoke all on function public.find_roots(text, text[]) from public, anon, authenticated;
grant execute on function public.find_roots(text, text[]) to service_role;
