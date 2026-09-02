# Langfive — RLS rollout runbook

## What this fixes

The Supabase anon key is public by design: it ships in the Next.js bundle and
inside the Chrome extension package. With RLS disabled, that key grants full
read/write on every table in `public` — every user's `userwords`, and the whole
`words`/`wordforms` corpus. The RPCs filter on `auth.uid()`, but direct
PostgREST table access bypasses them entirely.

## Status

| Item | State |
|---|---|
| `01_pre_rls_audit.sql` | Ready — read-only, safe on production |
| `20260814120000_enable_rls.sql` | Written, **tested against a local Postgres 16** — 17/17 adversarial cases pass, idempotent on re-run |
| `02_verify_rls.sql` | Ready |
| `LangBackend/auth.py` | Written — deny-by-default auth middleware |
| `LangBackend/app.py` | Patched — middleware wired in, CORS fixed. Backup at `app.py.pre_rls_backup` |
| SECURITY DEFINER RPC audit | **Blocked** — needs live database access |

## Blocked: the RPC audit

~20 RPCs are called from the frontend and extension. Only one
(`get_userwords_filtered`) has its body committed to the repo; the rest exist
only in the hosted project.

This matters because **a `SECURITY DEFINER` function ignores RLS completely**.
If any of those RPCs is `SECURITY DEFINER` and does not check `auth.uid()`
internally, it remains a hole straight through everything this migration does.
`get_known_words`, `move_words_to_userwords`, and `get_words_by_ids` are the
ones to look at hardest — the extension calls them with the public anon key.

I cannot read them from this session: the sandbox network blocks
`supabase.co` at the proxy, and the local device VM has no network at all.
Connecting the **Supabase connector** routes through Anthropic's
infrastructure and bypasses both. Once it is on, I can run the audit and
finish this.

## Order of operations

1. **Connect the Supabase connector**, scoped to this project. Prefer
   read-only mode for the audit step.
2. **Run `audit/01_pre_rls_audit.sql`.** Read-only. Two things to check before
   going further:
   - Section 2 — `service_role` must hold grants on every table the backend
     touches. `BYPASSRLS` skips row policies but **not** table grants. If a
     grant is missing, the backend breaks the moment RLS goes on, and it will
     look like an RLS problem when it is not. (This exact case failed in
     testing before I caught it.)
   - Sections 4/5 — the `SECURITY DEFINER` list. Do not skip this.
3. **Fix any RPC that is `SECURITY DEFINER` without an internal `auth.uid()`
   check**, before enabling RLS. Otherwise RLS gives false confidence.
4. **Apply `migrations/20260814120000_enable_rls.sql`.** Transactional — it
   either fully applies or not at all.
5. **Seed your admin row** (section 4 of the migration), otherwise `/validate`
   stops working for you too:
   ```sql
   select id, email from auth.users order by created_at limit 20;
   insert into public.user_roles (user_id, role) values ('<your-uuid>', 'admin')
   on conflict (user_id) do update set role = 'admin';
   ```
6. **Run `audit/02_verify_rls.sql`.** Sections 1–3 must return zero rows.
7. **Smoke-test the app**: log in, review vocabulary, open the extension on a
   YouTube page, load `/validate` as admin and as a normal user.
8. **Deploy the backend** with the new env vars (below).

## Rollback

```sql
-- Per table, if something breaks in production:
alter table public.<table> disable row level security;
```
The migration only adds policies and revokes `anon` writes; it drops no data.
`app.py.pre_rls_backup` restores the previous backend behaviour.

## Backend env vars (new)

Set on Koyeb before deploying:

- `ALLOWED_ORIGINS` — comma-separated. Defaults to
  `http://localhost:3000,https://langfive.com,https://www.langfive.com`.
  **Correct this to your real domains.**
- `EXTENSION_ID` — your published Chrome extension ID, so content-script
  requests (`Origin: chrome-extension://<id>`) are accepted.

`allow_origins=["*"]` with `allow_credentials=True` was invalid per the CORS
spec — browsers reject a wildcard origin on credentialed requests, so that
config was never doing what it appeared to.

## What the migration does

- **User-scoped tables** (any table with a `user_id` column) → owner-only
  CRUD via `user_id = (select auth.uid())`. The subselect wrapper makes
  Postgres evaluate `auth.uid()` once per query instead of once per row; on
  `userwords` this is a large difference.
- **Corpus tables** (no `user_id`) → `SELECT` for `authenticated`, writes
  gated behind `public.is_admin()`.
- **Tables that already have policies** (basejump: `accounts`, `account_user`,
  `invitations`, `billing_*`) → skipped entirely.
- **`user_roles`** → readable by its owner, writable by nobody through the
  API. Promotion happens via `service_role`/SQL editor only. This table is
  explicitly excluded from the generic rule; the generic user-scoped rule
  would have let any user insert their own admin row.

Classification is done by runtime introspection rather than a hardcoded table
list, so it adapts to whatever is actually in your database — including tables
neither of us has listed here.

## Test evidence

Run against Postgres 16 with a reconstructed Supabase environment
(`auth.uid()`, `anon`/`authenticated`/`service_role` roles):

```
PASS  anon reads corpus                 sees 0 words
PASS  anon writes corpus                DENIED
PASS  anon deletes wordforms            DENIED
PASS  alice reads userwords             only her own
PASS  alice reads BOB userwords         sees 0
PASS  alice writes row AS BOB           DENIED (violates RLS policy)
PASS  alice edits corpus                DENIED
PASS  alice SELF-PROMOTES to admin      DENIED      <-- escalation blocked
PASS  alice UPDATEs own role to admin   DENIED
PASS  admin edits corpus                ALLOWED
PASS  backend reads ALL userwords       sees all    <-- service_role unaffected
PASS  backend writes corpus             ALLOWED
                                        17 passed, 0 failed
```

Re-running the migration reports `skipped: 11` and changes nothing.

## Next: get the schema into the repo

This is the actual fix for agentic development being awkward. The problem was
never that the database is remote — it is that the schema isn't in the repo,
so nothing can read it, reason about it, or test against it.

```bash
cd Lang
supabase link --project-ref xpovcmbrttmkhnrfspvo
supabase db pull                 # dumps the live schema into a migration
supabase gen types typescript --linked > src/types/database.types.ts
supabase start                   # local Postgres + Auth
supabase db reset                # replay migrations + seed
```

Commit both the pulled schema and the generated types. After that, agents see
your real column names and RPC signatures instead of guessing, and you can
test policy changes locally before they reach production.

Move `supabase/` to the repo root while you are at it — the backend depends on
the same schema, so it is shared infrastructure rather than a frontend concern.
