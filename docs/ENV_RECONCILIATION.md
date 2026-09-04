# Env reconciliation — Koyeb + Vercel

Checked against what the code actually reads after the OpenRouter/DeepInfra
swap and the corpus move to R2. Ordered by blast radius.

---

## Koyeb (apps/api)

### Add — the API will not start without this

| Variable | Value |
|---|---|
| `OPENROUTER_API_KEY` | from https://openrouter.ai/keys |

`llm_client.py` raises at **import** time if this is missing, and `app.py`
imports it transitively via `nlp_processing`. Missing key = container never
comes up. This is deliberate — the old Azure setup failed later and more
confusingly — but it does mean the next deploy hard-fails until this is set.

### Add — silent degradation, no crash

| Variable | Value |
|---|---|
| `LANGFIVE_CORPUS_BUCKET` | `langfive-corpus` |
| `LANGFIVE_CORPUS_PREFIX` | `corpus/v1` |
| `LANGFIVE_CORPUS_ENDPOINT` | `https://a739b7b639d8e10c788645f3bab83f2f.r2.cloudflarestorage.com` |
| `AWS_REGION` | `auto` |
| `AWS_ACCESS_KEY_ID` | R2 **read-only** token (`langfive-corpus-api-readonly`) |
| `AWS_SECRET_ACCESS_KEY` | ditto |

This is the one to watch. The Dockerfile no longer bakes the corpus into the
image, so if these are unset the container starts perfectly happily, logs one
warning, and serves recommendations from an **empty corpus**. No exception, no
failed healthcheck — just quietly wrong output. Set these in the same deploy
as `OPENROUTER_API_KEY`, not after.

`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` are read implicitly by boto3,
which is why they don't appear in a grep of the source.

### Add — needed only if you transcribe

| Variable | Value |
|---|---|
| `DEEPINFRA_API_KEY` | from https://deepinfra.com/dash/api_keys |

Only `videoparsing.py` uses it, and the client is built lazily — the API runs
fine without it until something actually needs a transcript, then raises a
clear error.

### Add — probably a live bug right now

| Variable | Value |
|---|---|
| `EXTENSION_ID` | your published Chrome extension ID |
| `ALLOWED_ORIGINS` | explicit list including any Vercel preview domains |

`ALLOWED_ORIGINS` defaults to
`http://localhost:3000,https://app.langfour.com`.

Two consequences of leaving it at the default:

- The extension calls the API from content scripts, which send an
  `Origin: chrome-extension://<id>` header. That origin is only added to the
  allowlist when `EXTENSION_ID` is set. Unset today → **the extension's
  requests are being rejected by CORS.**
- Vercel preview deployments are served from `*.vercel.app`, which is not in
  the default list, so previews can't reach the API either.

### Remove — dead

| Variable | Why |
|---|---|
| `AZURE_OPENAI_API_KEY` | no longer read; chat moved to OpenRouter |
| `AZURE_OPENAI_ENDPOINT` | ditto |
| `OPENAI_API_KEY` | no longer read; Whisper moved to DeepInfra |
| `ANTHROPIC_API_KEY` | **never** read — no reference anywhere in the repo, before or after this change |

`ANTHROPIC_API_KEY` predates all of this. Worth revoking rather than just
deleting the row, since you can't tell from here whether it's still live.

### Rename

| From | To |
|---|---|
| `SUPABASE_KEY` | `SUPABASE_SERVICE_ROLE_KEY` |

`supabase_client.py` still accepts `SUPABASE_KEY` as a deprecated alias and
logs a warning, so this isn't urgent — but the name is the whole point. It
exists so nobody can look at the config and be unsure which key is in there.

**Check the value while you're in there.** `REQUIRE_SERVICE_ROLE` defaults to
`1`, and startup decodes the key's own `role` claim and refuses to boot if it
isn't `service_role`. If that variable currently holds an anon key, the next
deploy fails on purpose.

### Keep as-is

`SUPABASE_URL`. `REQUIRE_SERVICE_ROLE` can stay unset — it defaults to `1`,
which is what you want.

---

## Vercel (apps/web)

### Remove — and check what's in it first

| Variable | Why |
|---|---|
| `NEXT_PUBLIC_SUPABASE_KEY` | nothing in `apps/web/src` reads it |

Before deleting: **look at the value.** Everything prefixed `NEXT_PUBLIC_` is
inlined into the JavaScript bundle and shipped to every visitor's browser. If
this holds the anon key it's a harmless duplicate of
`NEXT_PUBLIC_SUPABASE_ANON_KEY`. If someone pasted the `service_role` key here
in September 2024, it has been public ever since and needs rotating in the
Supabase dashboard, not just deleting from Vercel.

The same stray variable is in your local `apps/web/.env`, which is how it
survived this long.

### Keep

`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY` — all three are read by the code.

### Not fixable with an env var

`src/app/components/UrlParser.tsx` reads `process.env.REACT_APP_API_URL`.
Next.js only inlines `NEXT_PUBLIC_*` into the browser bundle, so that read is
`undefined` no matter what you configure in Vercel, and the component falls
back to `http://localhost:8000` in production. Adding `REACT_APP_API_URL` to
Vercel will not help. The one-word fix is in the component.

---

## apps/extension

No hosting environment — Parcel inlines `REACT_APP_*` from
`apps/extension/.env` at build time, so whatever was in that file when you
last built is what shipped in the `.zip`. Nothing to change on a dashboard;
just make sure `REACT_APP_BACKEND_URL` points at Koyeb and not localhost
before the next `npm run build:ext`.

---

## Deploy order

1. Set `OPENROUTER_API_KEY` **and** the six corpus variables together.
2. Add `EXTENSION_ID` and an explicit `ALLOWED_ORIGINS`.
3. Deploy. Container fails fast and loudly if the OpenRouter key or the
   Supabase role is wrong.
4. Confirm the corpus actually landed — the startup log prints
   `corpus: <lang> ready (<n> files)` per language. If you see
   `corpus: no source configured`, step 1 didn't take.
5. Then delete the four dead variables and rename `SUPABASE_KEY`.

Locally, `python3 apps/api/scripts/check_llm.py` verifies the LLM half before
you deploy anything.
