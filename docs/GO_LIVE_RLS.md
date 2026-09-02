# Turning RLS on — everything is staged, three steps remain

RLS is **off** in production right now, exactly as it was this morning. Every
change below is either already applied and behaviour-neutral, or written and
tested but deliberately not applied.

---

## What is already done (applied to production, RLS still off)

**Phase 1 rolled back.** All 6 tables back to RLS off, policies dropped, anon
grants restored. Your recommender is working again.

**Function hardening applied.** Verified by clean A/B on a full local replica of
your schema with all 49 production functions: the *only* differences were three
functions going from error → working. Zero regressions.

| Change | Effect |
|---|---|
| Dropped `check_auth_uid()`, `test_auth_uid()` | debug leftovers, one was `SECURITY DEFINER` + anon-callable |
| Dropped `get_known_words(text)` | collided with the 3-arg overload, so any 1-arg call failed with "function is not unique" — dead code |
| 4 × `SECURITY DEFINER` → `SECURITY INVOKER` | no more RLS bypass; all already filtered on `auth.uid()`, so output is identical |
| Rebuilt `get_userwords_for_review(text)` | declared `timestamptz` but the column is `timestamp` — **threw on every call**. Now returns 30 rows |
| Added `get_user_counts_with_wordforms(_word_id)` | `useWordInfo.ts` has always called this with `_word_id`; the live function took no arguments, so the hook never worked |
| Dropped `word_info(uuid, integer)` | superseded; took a user id as a parameter instead of reading `auth.uid()` |
| Pinned `search_path` on all 43 remaining functions | closes search_path hijacking; cleared all 49 linter warnings |

Supabase advisors now report **zero** `SECURITY DEFINER` and **zero**
`search_path` findings. The only remaining errors are the 10 `rls_disabled`
ones, which are expected until step 3.

### Security definer vs invoker, briefly

- **`SECURITY INVOKER`** (the default) — the function runs as *whoever called
  it*, so RLS applies normally. Safe by default.
- **`SECURITY DEFINER`** — the function runs as its *owner* (`postgres`, a
  superuser) and RLS is skipped entirely. It is the database equivalent of
  `sudo`. Only safe if the function itself checks `auth.uid()`.

Your five DEFINER functions never needed elevation — each only touched the
caller's own rows plus the shared corpus, which ordinary policies allow. They
are now INVOKER, so the database enforces the rule rather than trusting the
function to. The one remaining DEFINER (`is_admin()`, created in step 3) is
genuinely necessary and is documented in that migration.

**Code changes made** (in your repo, not yet deployed):

- `LangBackend/supabase_client.py` — **new**. One client for all 9 files. Reads
  the key's own `role` claim at import and refuses to start unless it is
  `service_role`. This is what makes the anon-key mistake impossible to repeat
  silently.
- `LangBackend/database.py` — `initialize_cache()` now raises if the corpus
  loads zero words instead of serving wrong output forever.
- `LangBackend/{app,auth,cognates,language_flagging,language_flagging2,language_updating,recommender,backup_tables,test_script}.py`
  — all now import the shared client.
- `Lang/src/app/components/WordValidation.tsx` — all 4 corpus writes now use
  `.select()` and check the affected-row count, with an error banner. Without
  this, an RLS-blocked edit returns `{data: null, error: null}` and the page
  reports success while discarding the change.
- `Lang/src/app/hooks/useUpdateUserwords.ts` — the `userwords` lookup is now
  scoped to the current user. It previously read *every* user's rows, so a word
  any other user had marked `known` was silently dropped from your import.

Backups: `*.pre_rls_backup` next to each modified file.

---

## STEP 1 — Get the service_role key

1. Go to **https://supabase.com/dashboard/project/xpovcmbrttmkhnrfspvo/settings/api-keys**
   (Dashboard → project **Lang** → gear icon *Project Settings* → **API Keys**).
2. Find the row labelled **`service_role`**, marked *secret*.
3. Click **Reveal**, then copy it.

It is a JWT starting `eyJ...`. Paste it into https://jwt.io if you want to
confirm — the payload must read `"role": "service_role"`. The anon key you have
today reads `"role": "anon"`.

> Treat this key like a root password. It bypasses RLS entirely. It belongs only
> in backend environment variables — never in the Next.js app, never in the
> extension, never committed.

## STEP 2 — Replace it in Koyeb and redeploy

1. Koyeb dashboard → your **LangBackend** service → **Settings** →
   **Environment variables**.
2. **Add** `SUPABASE_SERVICE_ROLE_KEY`, type **Secret**, value from step 1.
3. **Delete** the old `SUPABASE_KEY`. (Leaving it is harmless — the new module
   prefers the new name and warns on the old one — but deleting removes the
   ambiguity that caused this.)
4. Leave `SUPABASE_URL` as it is.
5. Add `ALLOWED_ORIGINS` — your real domains, comma-separated.
6. Add `EXTENSION_ID` — your published Chrome extension ID.
7. **Redeploy.**

**Confirm it worked.** The service now refuses to boot with the wrong key, so a
clean startup is itself the proof. Check the logs for:

```
Supabase client authenticated as service_role.
Word cache loaded: {'spanish': ..., 'french': ..., 'german': ...}
```

If the key is still anon you will instead get a loud block of text and a
`RuntimeError` — deliberately, because the alternative is silent wrong output.

Then verify from the database side: Dashboard → **Logs** → **Edge**, filter
user agent `python-httpx`. The apikey role must now read `service_role`. If it
still reads `anon`, the deploy did not pick up the variable — **stop here.**

## STEP 3 — Turn RLS on

Only after step 2 is confirmed.

1. Apply `Lang/supabase/migrations/20260815110000_enable_rls_full.sql`.
   Covers all 10 tables: 6 user-scoped (own rows only), 4 corpus (read for
   signed-in users, write for admins), plus revoking the anonymous RPC surface.

2. **Make yourself an admin, or `/validate` stops working for you too:**
   ```sql
   select id, email from auth.users order by created_at limit 20;

   insert into public.user_roles (user_id, role)
   values ('<your-uuid>', 'admin')
   on conflict (user_id) do update set role = 'admin';
   ```

3. Smoke-test: log in, review vocabulary, open the extension on a YouTube page,
   import a deck, and open `/validate` — as admin (edits save) and ideally as a
   normal account (banner appears, nothing saves).

4. Re-run the advisors. The 10 `rls_disabled` errors should be gone.

### Test evidence for step 3

Run against a local replica built from your real schema and all 49 production
functions, hardened, then with full RLS applied:

- **39/39 RPCs byte-identical** with and without RLS, as a signed-in user. The
  only difference in the whole diff was a direct `select from userwords`
  returning 27 rows instead of 42 — one user no longer seeing another's rows.
- **17/17 adversarial cases pass**, including anonymous access fully denied,
  cross-user reads and writes denied, corpus edits denied for non-admins,
  allowed for admins, privilege escalation via `user_roles` blocked, and
  `service_role` unaffected.

Rollback is at the bottom of the migration file. It drops policies and disables
RLS; no data is touched.

---

## Still open, not blocking

- **3 rows in `userwords` have `user_id IS NULL`** — junk from the anonymous
  write path, now closed. Deleting is a destructive operation so I left it:
  `delete from userwords where user_id is null;`
- **`wordforms_duplicate`** — 304k rows, 172 MB, appears to be an abandoned
  copy of `wordforms`. Worth confirming and dropping.
- **Leaked-password protection is disabled** in Supabase Auth. One toggle,
  Dashboard → Authentication → Policies.
- **Schema still not in the repo.** After step 3, run `supabase db pull` and
  `supabase gen types typescript --linked` and commit both. Your migrations
  folder currently describes basejump tables that do not exist in this project.
- **Backend `SUPPORTED_LANGUAGES`** is `['spanish','french','german']` while
  Italian data files are still present — unrelated, but the cache guard will now
  surface it if a language ever loads empty.
