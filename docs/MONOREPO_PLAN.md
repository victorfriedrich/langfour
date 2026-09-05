# Langfive — monorepo improvement plan

Audited 16 Aug 2026 against the tree at `/Users/victorfriedrich/Langfive`.

The layout you have is already the right shape: `apps/{web,extension,api}` with
npm workspaces at the root. Most of what follows is about the things *around*
that shape — version control, the dev entrypoint, and a few pieces of the
restructure that were left half-finished.

Updated after two clarifications: the checked-in Supabase config isn't live
(section P1), and the corpus turns out to compress ~16× (section P0).

Ordered by what will hurt you if left alone.

---

## P0 — The repo is not under version control

There is no `.git` directory anywhere in the working tree. The three original
repositories are parked in `_to_delete/old-git-dirs/` (`web.git`, `api.git`,
`extension.git`, 215 MB total), and `_to_delete/partial-git-init/` contains a
half-finished `git init` — including a zero-byte `index.lock`, which is the
signature of a `git add` that was interrupted or killed.

Two consequences:

1. **Nothing you have done since the restructure is recoverable.** No commits,
   no stash, no reflog.
2. **`_to_delete/` is matched by `.gitignore`**, so even once you do commit,
   that history will never be captured. Do not empty that folder until you
   have decided what to do with it.

### Decide: fresh history, or preserved history

**Option A — fresh start (recommended).** The restructure moved essentially
every file; a preserved history would be mostly `R100` rename noise anyway,
and the three old repos remain readable on disk as archives.

```bash
cd ~/Langfive
rm -rf _to_delete/partial-git-init          # stale index.lock lives here
git init -b main
# do the P0 data-corpus work below FIRST, then:
git add -A
git commit -m "Monorepo: web, extension, api, supabase schema"
```

**Option B — preserve all three histories** via subtree merges. Real work,
and it produces a history where no single commit builds. Worth it only if you
routinely run `git log`/`git blame` on the pre-split code. If you want this,
say so and I will write the exact sequence.

Either way, archive the old repos somewhere outside the tree before deleting:

```bash
mv ~/Langfive/_to_delete/old-git-dirs ~/Archive/langfive-pre-monorepo-git
```

### Then: branch protection and a remote

Push to a private GitHub repo, and turn on "Require a pull request before
merging" for `main` even as a solo developer — it is what makes the CI in
section P3 meaningful rather than decorative.

---

## P0 — 2.2 GB of corpus is staged for git

`apps/api/data/processed/` is **2.2 GB across ~11,876 files**. This is almost
certainly what killed the earlier `git init && git add`.

The README justifies tracking it — "the recommender reads it at runtime and
Koyeb builds from the repository" — and that reasoning is sound for the
*deployment*, but it is the wrong tool for the *repository*:

- GitHub rejects pushes over 2 GB, and warns above 1 GB repo size.
- Every clone, every CI checkout, every branch switch pays the full cost.
- Git stores no delta for the `.npz` matrices; each regeneration adds a full
  new copy, permanently. The repo will only grow.

### It compresses ~16×

11,839 of the 11,844 files are JSON. On a 100-file sample: **21.2 MB raw →
1.3 MB gzipped, a 16.3× ratio**. Extrapolated, the whole corpus is roughly
**150 MB as four per-language tarballs** (the 4 `.npz` matrices are already
compressed and won't shrink).

That reframes the problem. Don't sync 11,876 individual objects — build one
archive per language, upload those, and have the container fetch and extract on
boot. Four objects instead of twelve thousand, a download measured in seconds,
and the storage bill drops below the point where it's worth thinking about.

The split is very lopsided, which helps: `es/` is 10,651 files / 1.9 GB, while
`de/` (418), `fr/` (437) and `it/` (333) together are ~260 MB. If the API only
serves one language per deployment, fetch only that tarball.

### Where to put it

| Option | Cost for 2.2 GB (~150 MB compressed) | Notes |
|---|---|---|
| **Cloudflare R2** (recommended) | **$0** | Free tier is 10 GB-month storage, 1M Class A ops/month, and egress is free always. You fit entirely inside it. S3-compatible API, so `boto3` works unchanged. |
| **AWS S3** | **~$0.05/month** | $0.023/GB-month in us-east-1. One-time upload of 4 archives is negligible; the first 100 GB/month of egress is free across all AWS services, which covers ~600 boot-time pulls of a 150 MB archive. |
| **Supabase Storage** | **$0 if you're on Pro, else $25/month** | The Free plan caps file storage at 1 GB and egress at 5 GB/month — the raw corpus doesn't fit, and even compressed you'd burn the egress cap in ~30 restarts. Pro includes 100 GB storage / 250 GB egress, so if your hosted project is already Pro this is free and saves you a second vendor. |
| **Bake into the image** | $0 | Archives copied in at build time, image pushed to a registry Koyeb pulls. No runtime fetch at all, but corpus updates require an image rebuild. |
| **Git LFS** | — | Not recommended. Free-tier LFS bandwidth is 1 GB/month; a couple of CI checkouts exhaust it, and deploy platforms need explicit LFS support. |

R2 if you want it free and separate; Supabase Storage if you're already on Pro
and would rather not add a vendor. Either way the code side is already done —
you have `LANGFIVE_DATA_DIR` and `paths.py`, so it's a download-and-extract step
at boot plus a small upload script.

Whatever you choose, the loose reference datasets at `apps/api/data/*.json`
(~20 MB total) are fine to keep in git. Also delete `data/yt_fr copy 2.json`
(2.5 MB, a Finder duplicate) while you are in there.

**Until this is resolved, do not run `git add -A`.** Add
`apps/api/data/processed/` to `.gitignore` first if you want to commit the
rest today and solve the corpus properly next week.

---

## P1 — `supabase/` describes a project you don't run

You've confirmed none of the checked-in Supabase config is live, and the code
agrees. Nothing in `apps/web/src` or `apps/extension/src` references
`basejump`, `billing-functions`, `billing-webhooks`, or `functions.invoke`.
What's actually in the folder:

- **12 migrations**, 5 of them [Basejump](https://usebasejump.com) — a
  SaaS starter kit providing personal/team accounts, invitations, and Stripe
  billing. That's the "supabase-adjacent project" you were thinking of.
- **15 pgTAP tests** under `tests/database/` covering team accounts,
  invitations, account roles and billing functions — all Basejump features, none
  of which your apps call.
- **2 edge functions**, never invoked from either client.
- **The RLS work** (`enable_rls`, `rls_phase1_user_scoped`,
  `enable_rls_full`, `function_hardening`, `audit/`, `tests/rls/`) — this is
  the part that looks genuinely yours.

Supabase *the service* is load-bearing: `apps/api/supabase_client.py` is
imported across the API. Supabase *the folder* is scaffolding from a template.
The risk isn't that it's dead weight, it's that it's **misleading** — `npm run
db:reset` would build a local database whose schema doesn't match the hosted one
you actually query, and any future `db:diff` compares against fiction.

### Decision: delete it

Agreed for the Basejump scaffolding — it describes a product you're not
building, and pgTAP tests for team invitations you'll never run are worse than
no tests.

**One caveat, since the RLS rollout is still planned.** Deleting the folder also
deletes the four migrations that *implement* RLS (`enable_rls`,
`rls_phase1_user_scoped`, `enable_rls_full`, `function_hardening`) plus the
attack-test suite in `tests/rls/` and the audit queries in `audit/`. Those were
written against the schema in this folder, so they may not apply cleanly to your
real hosted project — but they encode the thinking, and rewriting them from
scratch when you do the rollout is a waste.

Suggested split:

```bash
# keep the RLS thinking as reference material
mkdir -p docs/rls-reference
mv supabase/audit supabase/tests/rls docs/rls-reference/
mv supabase/migrations/20260814120000_enable_rls.sql \
   supabase/migrations/20260814140000_rls_phase1_user_scoped.sql \
   supabase/migrations/20260815100000_function_hardening.sql \
   supabase/migrations/20260815110000_enable_rls_full.sql \
   docs/rls-reference/

# the rest is Basejump scaffolding for a project you don't run
rm -rf supabase/
```

They live in `docs/` as reference, not as migrations something might try to
apply. When you do the rollout against the hosted project, adapt the policies
from there rather than starting cold.

Consequences for the rest of this plan:

- **All `db:*` scripts come out of the root `package.json`.** They target a
  local stack that no longer exists. Removed from the snippet below.
- **`supabase` leaves `devDependencies` too** — no CLI, nothing to run.
- **`packages/database-types` (P2) is off the table** for now, since
  `supabase gen types --linked` needs a linked project. If you later want typed
  queries without adopting migrations, you can run `supabase link` + `gen types`
  as a one-off and commit the output by hand.
- **Do the RLS rollout against the hosted project directly**, using
  `docs/GO_LIVE_RLS.md` and the reference SQL. Worth reconsidering `supabase
  link` + `db pull` at that point — a schema baseline is most valuable exactly
  when you're about to change security policy on a live database.

Note the `.env.example` in the repo hardcodes `SUPABASE_PROJECT_REF` and
`SUPABASE_URL` as `xpovcmbrttmkhnrfspvo`. If that's not the project you're
actually using, it's a trap for future-you — fix or blank it.

---

## P1 — One command to start everything

This is the ask. Three problems block it today:

1. `npm run dev` only starts the web app.
2. `api:dev` shells into `apps/api` and calls `uvicorn` from whatever Python
   happens to be on `PATH` — no virtualenv, so it works on your machine and
   nowhere else.
3. Six of the fourteen scripts are `db:*` commands against a local Supabase
   stack you don't run, and `db:types` writes into a `packages/` directory that
   has never existed.

### Replacement root `package.json`

```json
{
  "name": "langfive",
  "version": "1.0.0",
  "private": true,
  "description": "Langfive monorepo — web app, Chrome extension, API, and shared Supabase schema.",
  "packageManager": "npm@10.9.0",
  "engines": { "node": ">=20" },
  "workspaces": ["apps/web", "apps/extension", "packages/*"],

  "scripts": {
    "setup": "npm install && npm run setup:env && npm run setup:py",
    "setup:env": "node scripts/setup-env.mjs",
    "setup:py": "python3 -m venv apps/api/.venv && apps/api/.venv/bin/pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt",

    "dev": "concurrently -n web,api -c cyan,magenta -k \"npm:dev:web\" \"npm:dev:api\"",
    "dev:web": "npm run dev --workspace=lang-frontend",
    "dev:api": "cd apps/api && .venv/bin/uvicorn app:app --reload --port 8000",
    "dev:ext": "npm run start --workspace=spotlight-lingo",
    "dev:all": "concurrently -n web,api,ext -c cyan,magenta,yellow -k \"npm:dev:web\" \"npm:dev:api\" \"npm:dev:ext\"",

    "build": "npm run build --workspaces --if-present",
    "lint": "npm run lint --workspaces --if-present && apps/api/.venv/bin/ruff check apps/api",
    "typecheck": "npm run typecheck --workspaces --if-present",
    "test": "npm run test --workspaces --if-present && apps/api/.venv/bin/pytest apps/api"
  },

  "devDependencies": {
    "concurrently": "^9.1.0",
    "prettier": "^3.3.3"
  }
}
```

Notes on the choices:

- `concurrently -k` kills every child when one dies, so `Ctrl-C` leaves nothing
  orphaned on port 8000. `npm:dev:web` shorthand keeps the definitions in one
  place.
- Per your preference, `dev` is **web + api**. `dev:all` adds the extension
  watcher when you want it.
- `dev:api` runs uvicorn from `apps/api/.venv/bin`, so it does not depend on
  which Python is active in the shell. Add `apps/api/.venv/` to `.gitignore`.
- No `db:*` scripts and no `supabase` CLI dependency, per the decision above —
  both apps talk to the hosted project directly.
- `engines` raised to `>=20`: Next 14 and the Supabase CLI both want it, and
  your machine is on Node 22.

Add `.nvmrc` at the root containing `22` so the version is not folklore.

### `scripts/setup-env.mjs`

The README currently asks you to copy `.env.example` into three places by
hand. A ~20-line script that copies it to `apps/web/.env`, `apps/extension/.env`
and `apps/api/.env` when they do not already exist (never overwriting) turns
onboarding into `npm run setup`. Happy to write it.

---

## P1 — npm workspace hygiene

Three things are wrong and all are one-liners:

**Stale per-app lockfiles.** `apps/web/package-lock.json` and
`apps/extension/package-lock.json` both exist; there is no root lockfile. With
workspaces, the root lockfile is the source of truth and the per-app ones are
actively harmful — they diverge, and `npm ci` in the wrong directory installs a
different tree than `npm install` at the root.

```bash
rm apps/web/package-lock.json apps/extension/package-lock.json
npm install                        # regenerates a single root package-lock.json
```

Commit that root lockfile.

**The `supabase` CLI is a runtime dependency of two apps.** It appears in
`apps/web` (`^1.192.5`) *and* `apps/extension` (`^1.200.3`) `dependencies`. It
is a build-time CLI, it is ~40 MB of platform binaries, and two different
versions in one workspace tree is a coin flip as to which one `npx supabase`
resolves. Remove from both; the root `devDependencies` entry above covers it.

**Node version drift.** `@types/node` is `^20` in web and `^22.4.1` in
extension. Harmless today, but pin both to `^22` alongside the `.nvmrc`.

---

## P2 — Add a `packages/` layer for the things both clients share

There is no `packages/` directory, and it shows in two places:

**Database types.** Neither app has generated Supabase types. `apps/web` has
one `.d.ts` (for `canvas-confetti`), `apps/extension` has one (for
`wink-pos-tagger`) — the actual database shape is untyped everywhere, which
with RLS still to come is where I'd expect the next class of bug: RLS failures
are silent (rows just vanish, HTTP 200), and untyped queries give you no help
finding them.

Since you're dropping `supabase/`, this becomes a one-off rather than a wired-up
script — but it's still worth doing:

```bash
npx supabase login
npx supabase link --project-ref <your-real-project-ref>
npx supabase gen types typescript --linked > packages/database-types/index.ts
```

```
packages/database-types/
├── package.json      { "name": "@langfive/database-types", "types": "index.ts" }
└── index.ts          # generated, committed by hand, regenerated when schema changes
```

Then `createClient<Database>(url, key)` in both apps, and every `.from()` call
gets checked. Re-run the generate command whenever you change the schema in the
dashboard; a stale file is still better than none.

**The Supabase client.** `apps/web/src/lib/supabaseclient.ts` and
`apps/extension/src/supabaseclient.ts` are near-identical — they differ only in
the env prefix (`NEXT_PUBLIC_` vs `REACT_APP_`) and the extension's extra
`ensureSupabaseSession`. A `packages/supabase-client` exporting a factory that
takes url + key, with each app passing its own env vars, removes the drift risk
without fighting either bundler over env handling.

This is the one place I would *not* over-invest: two call sites is a weak case
for a shared package. Do `database-types` for sure; do `supabase-client` only
if you find yourself fixing the same auth bug twice.

---

## P2 — The Python app needs the same treatment the JS side got

`apps/api` has 42 Python files at its top level. **18** of them are never
imported by anything — one-off scripts such as `quickfix.py`,
`backup_tables.py`, `reparse.py`, `wordconverter.py` *and* `wordconverter2.py`,
`language_flagging.py` *and* `language_flagging2.py`, `sel.py`, and four
`*parser*.py` files. Another 3 are tests. They are indistinguishable from the
service at a glance, and the Dockerfile copies all of them into production.

```
apps/api/
├── pyproject.toml          # deps, ruff, pytest config in one place
├── .python-version         # 3.11, matching the Dockerfile
├── src/langfive_api/       # the ~21 modules the service actually imports
├── scripts/                # the 18 one-off / maintenance scripts
├── tests/                  # test_flashcards.py, test_media_import.py, test_script.py
└── data/
```

The `2`-suffixed pairs are worth a look before moving anything — one of each is
probably superseded, and this is the moment to find out.

**Resolved 5 Sep 2026**, ahead of the restructure. The pairs were superseded, as
suspected: `wordconverter2.py` (batched and resumable) and `language_flagging.py`
(the developed prompt) survived under unsuffixed names, and their counterparts
were deleted. Also deleted: `quickfix.py`, `italian_beginner.py` and
`spanishparser2.py`, all of which ran their work at import time against input
files no longer in the tree, and `test_script.py`, a scratch REPL file that
pytest collected as 11 assertion-free tests. `backup_tables.py` moved to
`scripts/`. The counts above are from the 16 Aug audit and predate this;
`sel.py` and the scrapers named there are gone too, removed with the ingestion
pipeline rewrite. What remains unimported at the top level is eight one-off
maintenance scripts, still awaiting the `src/` + `scripts/` split below.

Even without the `src/` move, three cheap wins:

- **Split the requirements.** `pytest==8.3.2` is in `requirements.txt`, so it
  ships to production. Move it and `ruff` to `requirements-dev.txt`.
- **Move the three `test_*.py` files into `tests/`.** Right now `pytest` from
  the wrong directory collects nothing.
- **Add a `.dockerignore` at the repo root.** The Dockerfile builds from the
  repository root, so the current build context is **~2.4 GB** — the whole
  corpus *plus* the 215 MB of old `.git` directories in `_to_delete/`. Every
  `docker build` uploads all of it to the daemon.

```
# .dockerignore
node_modules
**/node_modules
_to_delete
.git
apps/web
apps/extension
supabase
docs
**/.venv
**/__pycache__
**/.DS_Store
```

Also: `apps/api/.gitignore` is the stock GitHub Python template and contradicts
the root file in places (it ignores `lib/`, `build/`, `articles/`). Since the
root `.gitignore` already covers Python properly, delete the app-level one or
cut it down to genuinely API-specific entries.

---

## P2 — Committed build output and dead assets

**Extension source tree contains compiled output.** `apps/extension/src` holds
19 `.ts` files alongside 23 `.js` and 19 `.js.map` files. Parcel regenerates
these; keeping them means every edit produces a diff in two files, and imports
can silently resolve to a stale `.js`.

```bash
rm apps/extension/src/*.js.map
# then delete each .js that has a matching .ts sibling (19 of them).
# Four have no .ts twin and are real sources — keep these:
#   api-service.js  backgroundScript.js  reader.js  youtubeBookmark.js
```

Those four are worth converting to TypeScript eventually; `backgroundScript.js`
in particular is where extension bugs tend to hide.

Then add to `.gitignore`:

```
apps/extension/src/**/*.js.map
```

**14 MB of duplicated web assets.** `apps/web/src/app/public/` contains
`documentreader.webp` (12 MB) and `videotranslation.webp` (2.4 MB), both
byte-identical (md5-verified) to the copies in `apps/web/public/`, plus an
unreferenced `mockup.png`. Next.js only serves from the project-root `public/`,
and the one reference (`ExtensionGuide.tsx`, `src="/documentreader.webp"`)
resolves to the correct copy. `apps/web/src/app/public/` is dead weight; delete
the whole directory.

While there: a 12 MB `.webp` served as a static asset is a slow landing page.
Resize to display dimensions and it should drop to a few hundred KB.

**`.DS_Store` files are committed** in five locations including
`apps/api/data/processed/`. The root `.gitignore` covers them, but they exist
on disk today, so remove them before the first commit:

```bash
find ~/Langfive -name .DS_Store -not -path '*/_to_delete/*' -delete
```

---

## P3 — CI, formatting, and the docs

**No `.github/workflows/`.** A single `ci.yml` on pull requests covering
`npm ci`, `npm run lint`, `npm run typecheck`, `npm run build`, and `pytest`
would catch most of what the current setup cannot.

One thing must change first for CI to mean anything:
`apps/web/next.config.mjs` sets both `eslint.ignoreDuringBuilds: true` and
`typescript.ignoreBuildErrors: true`. A green build currently proves the
bundler ran, nothing more. Turn typescript checking back on, fix the fallout
(often small), and keep the eslint escape hatch only if the backlog is large.

**Formatting is per-app and inconsistent.** `apps/extension` has a
`.prettierrc` and `.eslintrc.js`; `apps/web` has `.eslintrc.json` plus an
inline `eslintConfig` block in its `package.json` that disables
`no-unused-vars` in both flavours. Move Prettier to a single root
`.prettierrc`, add a root `.editorconfig`, and let each app keep only its
framework-specific ESLint config.

**Docs.** The README references `docs/RLS_IMPACT_FULL.md`, which does not
exist — `docs/` has `CONTINUITY_EVIDENCE.md`, `GO_LIVE_RLS.md` and
`RLS_RUNBOOK.md`. Either restore the file or fix the link. The README's Quick
start section also needs rewriting once `npm run setup` and `npm run dev` exist,
since the current instructions are four manual steps.

Neither `apps/api` nor the root explains how to run the API's tests. A short
"Development" section per app README, or a single root one, is enough.

---

## Suggested order of work

1. Archive `_to_delete/old-git-dirs`, delete `partial-git-init`.
2. Decide the corpus strategy; gitignore `data/processed/` in the interim.
3. Move the RLS SQL to `docs/rls-reference/`, delete the rest of `supabase/`.
4. `git init`, first commit, push to a private remote.
5. Delete the two per-app lockfiles, remove `supabase` from app deps,
   `npm install` at root, commit the root lockfile.
6. New root `package.json` + `concurrently` + `.nvmrc` → `npm run dev` works.
7. `scripts/setup-env.mjs` → `npm run setup` works.
8. Root `.dockerignore`, requirements split, tests into `tests/`.
9. Delete `apps/web/src/app/public/`, the `.js.map` files, the `.DS_Store`s.
10. `packages/database-types`, generated once against the hosted project.
11. CI workflow; re-enable TypeScript checking in `next.config.mjs`.

Steps 1–6 are an afternoon and give you the one-command start. The rest can
land incrementally.
