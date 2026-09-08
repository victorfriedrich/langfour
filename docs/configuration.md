# Configuration

Every environment variable, where to get it, and what a from-scratch setup
cannot reproduce. For how the pieces fit together, see
[architecture.md](architecture.md).

**Contents**

- [What you need accounts for](#what-you-need-accounts-for)
- [`apps/web` and `apps/extension`](#appsweb-and-appsextension)
- [`apps/api`](#appsapi)
- [The corpus bucket](#the-corpus-bucket)
- [Setting up from scratch](#setting-up-from-scratch)

Three `.env` files, one per app, each with a `.env.sample` that documents every
value. There is no root `.env` on purpose: the web and extension files ship to
users in the bundle, the API file holds secrets, and one shared file is how a
secret ends up in a browser bundle.

## What you need accounts for

| Service | Needed for | What it costs |
|---|---|---|
| [Supabase](https://supabase.com) | everything | free tier |
| [OpenRouter](https://openrouter.ai) | API boot; translation, dictionary growth, channel classification | `deepseek-v4-flash` is $0.07 in / $0.17 out per million tokens, `v4-pro` $0.72 / $1.44. Parsing a whole transcript into the dictionary costs a fraction of a cent |
| [DeepInfra](https://deepinfra.com) | transcribing videos that have no captions | $0.0002 per minute of audio: a 20-minute video is 0.4 cents, an hour is 1.2 cents |
| [Cloudflare R2](https://developers.cloudflare.com/r2/) | corpus download in production only | free: 10 GB storage, egress never billed. The corpus is 137 MB |
| Google Cloud, YouTube Data API v3 | the discovery pipeline only | free, 10,000 quota units per day |

Only Supabase and OpenRouter are needed to run the app locally.

## `apps/web` and `apps/extension`

Both are public bundles and hold the same three values under different names.
Nothing secret can live in either.

| Web | Extension | Where to get it |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `REACT_APP_SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `REACT_APP_SUPABASE_ANON_KEY` | same page → `anon` `public`. Public by design, constrained by RLS |
| `NEXT_PUBLIC_API_URL` | `REACT_APP_BACKEND_URL` | the API origin. Both fall back to a default, so a missing value fails quietly rather than loudly |

## `apps/api`

| Variable | Where to get it | Notes |
|---|---|---|
| `SUPABASE_URL` | Project Settings → API → Project URL | |
| `SUPABASE_SERVICE_ROLE_KEY` | Project Settings → API Keys → `service_role` → Reveal | bypasses RLS; the API decodes the key's `role` claim at boot and refuses to start on anything else (`REQUIRE_SERVICE_ROLE=0` disables the check) |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | required at import time |
| `LLM_MODEL_SMART`, `LLM_MODEL_FAST` | any OpenRouter slug | defaults `deepseek/deepseek-v4-pro` and `deepseek/deepseek-v4-flash` |
| `DEEPINFRA_API_KEY` | [deepinfra.com/dash/api_keys](https://deepinfra.com/dash/api_keys) | transcription only; the API boots without it |
| `LLM_MODEL_TRANSCRIBE` | | default `openai/whisper-large-v3-turbo` |
| `ALLOWED_ORIGINS` | | comma-separated CORS allowlist; default is localhost and `app.langfour.com` |
| `EXTENSION_ID` | `chrome://extensions` with Developer mode on | adds `chrome-extension://<id>` to the allowlist. `manifest.json` pins the extension `key`, so the ID is the same on every machine |
| `YOUTUBE_API_KEY` | Google Cloud Console → enable *YouTube Data API v3* → Credentials | the discovery pipeline only, never read by the API. When that API returns 403 it echoes the full request URL, key included, so the pipeline redacts it before anything is stored |

## The corpus bucket

In production the container starts empty and pulls the transcript corpus from
object storage at boot. Locally nothing needs to be set: an existing
`apps/api/data/processed/` is used as-is, and with neither source configured
the recommender simply starts with whatever is on disk.

The store is Cloudflare R2, chosen because it is S3-compatible and never bills
egress, so redeploys that re-download 137 MB cost nothing. The `LANGFIVE_`
prefix on these names predates the Langfour rename and stays because changing
it means changing the deployed environment, the bucket and its token together.

Layout inside the bucket, written by `npm run corpus:pack` and
`npm run corpus:upload`:

```
langfive-corpus/
└── corpus/v1/
    ├── de.tar.gz          4 MB     each unpacks to processed/<lang>/
    ├── es.tar.gz          121 MB
    ├── fr.tar.gz          7 MB
    ├── it.tar.gz          5 MB
    └── MANIFEST.txt       sizes and SHA-256 per archive
```

To set it up: create a bucket in the Cloudflare dashboard under R2, then under
*Manage R2 API Tokens* create two tokens, one **Object Read only** for the API
and one Object Read & Write for uploads from your laptop. The S3 endpoint is on
the bucket's Settings page.

| Variable | Value |
|---|---|
| `LANGFIVE_CORPUS_BUCKET` | the bucket name |
| `LANGFIVE_CORPUS_PREFIX` | `corpus/v1` |
| `LANGFIVE_CORPUS_ENDPOINT` | `https://<account-id>.r2.cloudflarestorage.com` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | the read-only token |
| `AWS_REGION` | `auto` |

Two optional knobs: `LANGFIVE_CORPUS_LANGUAGES` restricts the download (without
`es` it is 16 MB), and `LANGFIVE_DATA_DIR` moves `data/` onto a mounted volume
so the corpus survives restarts. Any S3-compatible store works in place of R2,
and `LANGFIVE_CORPUS_BASE_URL` accepts a plain HTTPS prefix instead of the
bucket block. `upload_corpus.sh` refuses to push more than 2 GB by default,
because R2's budget alerts are informational and there is no server-side cap.

## Setting up from scratch

A fresh Supabase project cannot be recreated from this repo alone: the tables
and the ~50 RPC functions the clients call live only in the hosted project.
[`apps/api/sql/supabase_schema.md`](../apps/api/sql/supabase_schema.md) lists
what would have to exist, down to the policies and indexes, and the two SQL
files beside it are the runbooks that were applied by hand.

Everything else is reproducible. The corpus rebuilds from the discovery
pipeline and `ingest.py`, and the dictionary grows itself as text is parsed.
