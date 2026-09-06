# Langfour

Monorepo for Langfour: a Next.js web app, a Chrome extension, and a FastAPI
backend. Deployed at [langfour.com](https://langfour.com).

> **A note on the name.** The product is Langfour everywhere it is
> user-visible. Internal identifiers still carry an earlier `langfive`
> prefix — the `LANGFIVE_*` environment variables, the `langfive-corpus`
> bucket, the `langfive-corpus-api-readonly` role and the `langfive-api`
> image tag. Those are load-bearing: renaming them means changing the
> deployed environment, the bucket and the IAM role in lockstep, which
> buys nothing. They are left alone deliberately.

```
langfour/
├── apps/
│   ├── web/          Next.js 14 app          (npm workspace: lang-frontend)
│   ├── extension/    Chrome extension        (npm workspace: spotlight-lingo)
│   └── api/          FastAPI + NLP pipeline  (Python)
│       ├── corpus_sync.py  fetches the transcript corpus at boot
│       ├── paths.py        all filesystem locations
│       ├── scripts/        one-off and maintenance scripts
│       └── data/           corpora & reference datasets (see below)
├── docs/
└── package.json      npm workspaces
```

All three talk to a hosted Supabase project. There is no `supabase/` directory:
the schema is managed in the dashboard, not as migrations in this repo.

## Quick start

```bash
npm install
pip install -r apps/api/requirements-dev.txt

cp apps/web/.env.sample       apps/web/.env
cp apps/extension/.env.sample apps/extension/.env
cp apps/api/.env.sample       apps/api/.env    # then fill in the blanks

npm run dev                  # web on :3000 + api on :8000
npm run dev:ext              # extension watch build, when you need it
```

## Environment variables

Two different keys, and the distinction matters:

| Key | Used by | Ships to users? | Bypasses RLS? |
|---|---|---|---|
| `anon` | web, extension | **Yes** — in the JS bundle and the extension zip | No |
| `service_role` | api only | No — server-side only | **Yes** |

The `anon` key is public by design. The `service_role` key is not: it ignores
row-level security completely and must never appear in `apps/web` or
`apps/extension`.

`apps/api/supabase_client.py` reads the key's own `role` claim at startup and
refuses to boot if it is not `service_role`, because the failure mode otherwise
is silent — with RLS on, an `anon` key makes every query return zero rows with
HTTP 200 and no error anywhere.

Each app has its own `.env.sample` documenting exactly what it needs and
where to get it. There is no root `.env` — the three apps have different
trust levels, and one shared file is how they drift out of sync.

## LLM providers

Chat completions go through **OpenRouter**; speech-to-text goes to
**DeepInfra**. Neither OpenAI nor Azure is called any more.

Both speak the OpenAI wire protocol, so there is one SDK (`openai`) pointed at
two base URLs. `apps/api/llm_client.py` is the only place a client is
constructed; `apps/api/models.py` is the only place a model is named.

| | Provider | Default model | Env |
|---|---|---|---|
| Judgement / structured output | OpenRouter | `deepseek/deepseek-v4-pro` | `LLM_MODEL_SMART` |
| High-volume mechanical work | OpenRouter | `deepseek/deepseek-v4-flash` | `LLM_MODEL_FAST` |
| Transcription | DeepInfra | `openai/whisper-large-v3-turbo` | `LLM_MODEL_TRANSCRIBE` |

Swapping models is a config change, not a code change — every call site refers
to `MODEL_SMART` or `MODEL_FAST`, never to a literal.

Two things worth knowing before you touch this:

- **OpenRouter cannot transcribe.** It proxies chat completions only, with no
  `/audio/transcriptions` route. That is the entire reason DeepInfra is here.
  Only `videoparsing.py` needs it, and its client is built lazily, so the API
  starts without a DeepInfra key.
- **Structured output support varies by model and by whichever provider
  OpenRouter routes you to.** `llm_client.parse_structured()` tries strict
  `json_schema` first, falls back to plain JSON mode, and validates with
  Pydantic either way. The validation is the actual contract; the
  `response_format` is an optimisation. It replaced
  `client.beta.chat.completions.parse()`, which is OpenAI-SDK-specific and
  assumes strict schema support that DeepSeek does not reliably have.

## The transcript corpus

`apps/api/data/processed/{de,es,fr,it}/` is the video transcript corpus:
**~2.2 GB across ~11.8k JSON files**. It is deliberately **not in git** and
**not baked into the container image**. It compresses ~16×, so it ships as one
gzipped tarball per language — **134 MB total** — in an S3-compatible bucket.

```bash
apps/api/scripts/pack_corpus.sh                  # processed/ -> data/archives/*.tar.gz
apps/api/scripts/upload_corpus.sh <bucket> [endpoint] [prefix]
```

At startup `corpus_sync.py` pulls each language onto local disk, skipping any
that is already there. Configure it with `LANGFIVE_CORPUS_BASE_URL` (plain
HTTPS, public or presigned) or `LANGFIVE_CORPUS_BUCKET` + friends (any
S3-compatible store: Cloudflare R2, AWS S3, Supabase Storage). With neither
set, an existing `data/processed/` is used as-is and nothing is downloaded —
which is the normal case in local development.

The extraction is streaming by design: **20 MB peak RSS to unpack 1.99 GB**.
`corpus_sync.py` documents which three details keep it flat; read that
docstring before changing it.

The split is lopsided — Spanish is 10,651 of the files and 118 MB of the
134 MB. A deployment that serves fewer languages should set
`LANGFIVE_CORPUS_LANGUAGES`.

### The rest of `data/`

- `yt_es.json` and `french.json` — the two reference datasets still read by
  code: an ingestion ledger and the dictionary seed list. Tracked.
- `articles/`, `archives/`, `downloaded_files/`, `youtube_thumbnails/` —
  runtime output, regenerable, gitignored.

Nothing reads these by relative path. Everything resolves through
`apps/api/paths.py`, so the API runs correctly from any working directory. Set
`LANGFIVE_DATA_DIR` to relocate the corpus onto a volume.

## Deployment

The API image builds from the **repository root**, not `apps/api`:

```bash
docker build -f apps/api/Dockerfile -t langfive-api .
```

The root `.dockerignore` is what keeps that context small — without it the
build context is ~2.4 GB.

## Row-level security

RLS is **on** for every table in `public`, and the API is the only component
holding a `service_role` key. Each client reaches its own rows through the
RPCs, which run as the caller.

The rollout ordering was not optional: the API had to be running with
`service_role` before the policies went on, for the reason above — an `anon`
key under RLS returns zero rows with HTTP 200 rather than an error.

`apps/api/sql/supabase_schema.md` inventories every table, policy and function
with the client that calls it. The schema itself lives in the Supabase project,
not in this repo.
