# Does RLS break Langfive? — empirical answer

**No. One behaviour changes, and it is a bug fix.**

You said continuity matters more than security right now, and that adding RLS
should not break anything. Rather than argue the point, I tested it.

## Method

Production was not touched. I rebuilt your database locally:

- Real schema pulled from `pg_catalog` on project `xpovcmbrttmkhnrfspvo` —
  all 10 tables with exact columns, types, defaults, constraints and indexes.
- **All 49 production functions**, verbatim via `pg_get_functiondef`.
- A stub `auth.uid()` plus the `anon` / `authenticated` / `service_role` roles.
- Synthetic data shaped like production: 3 users, 60 words, 60 wordforms,
  40 userwords split across two users, flashcard tests, translations.

Then two **fresh, identical** databases — one without RLS, one with the
migration applied *before* any writes, so cumulative state can't confound the
comparison. Each got exactly one identical harness run: every RPC the
frontend, the extension, and the backend actually call — 36 calls as a
signed-in user, 3 as `service_role`, plus the direct table reads.

## Result

```
diff no-RLS  vs  RLS
37c37
< alice-table,(select count(*) from userwords),42
---
> alice-table,(select count(*) from userwords),27
```

That is the **entire** diff. One line.

- **39 of 39 RPCs: byte-identical results.** Nothing broken, no row counts
  changed, no new errors.
- The one change: a direct `select from userwords` returns 27 rows instead of
  42 — Alice stops seeing Bob's 15 rows. That is precisely the isolation RLS
  exists to provide.
- `service_role` (your FastAPI backend): completely unaffected, as expected.
- Corpus reads (`words`, `wordforms`): 60 → 60, unchanged for signed-in users.

**Why nothing breaks:** every one of your RPCs already filters on
`auth.uid()` internally. RLS re-states a constraint the functions were
enforcing anyway, so it is a no-op for them.

## RLS actually fixes a live bug

`useUpdateUserwords.ts` queries userwords without a user filter:

```ts
.from('userwords').select('word_id').eq('status','known').in('word_id', uniqueWordIds)
```

With RLS off this reads **every user's** rows. So if any other user has marked
a word `known`, that word is silently dropped from *your* import — the words
never get added and the user never sees why. With RLS on, the query is scoped
to the caller and the import behaves correctly.

This is a real, current, user-visible bug that RLS closes.

## Pre-existing breakage found (unrelated to RLS)

These fail identically before and after, so they are not RLS risks — but they
are broken in production right now:

| Function | Problem |
|---|---|
| `get_userwords_for_review(text)` | `structure of query does not match function result type` — throws on every call |
| `get_known_words(text)` | Ambiguous: matches both the 1-arg and the 3-arg-with-defaults overload |
| `get_user_words_with_tests` | Three overloads; ambiguous on positional args |
| `get_user_counts_with_wordforms` | Frontend calls it with `{_word_id}`, but the live signature takes **no arguments** |

That last one means `useWordInfo.ts` has never worked.

## The schema/repo gap

Your `Lang/supabase/migrations/` contains basejump migrations. **None of the
basejump tables exist in the live project** — no `accounts`, `account_user`,
`invitations`, or `billing_*`. None of your 10 real tables and none of your 49
functions have DDL in the repo.

The repo and the database have essentially nothing in common. That, not
Supabase, is why agentic development feels awkward — there is nothing on disk
for a tool to read.

## Recommendation

The migration is safe to apply on this evidence. If you want to sequence it
even more conservatively, apply in this order:

1. **`move_words_to_userwords(_word_ids integer[])`** — revoke `anon` EXECUTE.
   This is `SECURITY DEFINER` and anon-callable, and `userwords.user_id` is
   nullable, so anyone with the public key can insert junk rows. There are
   already **3 rows with `user_id IS NULL`**. RLS alone does not close this;
   `SECURITY DEFINER` ignores RLS. Zero continuity risk — signed-in users are
   unaffected.
2. **RLS on user-scoped tables only** (`userwords`, `userdata`,
   `usertranslations`, `flashcardtests`, `videos_seen`, `userwordinteraction`).
   Proven no-op above.
3. **RLS on corpus tables** (`words`, `wordforms`, `wordforms_duplicate`,
   `languagelevels`) — this is the step that gates `/validate` behind admin,
   so it is the only one with a visible behaviour change, and only for you.
4. **`supabase db pull`** to finally get the schema into the repo.

Steps 1–2 carry no continuity risk on this evidence. Step 3 changes exactly
one page, for admins only.
