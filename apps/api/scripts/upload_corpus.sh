#!/usr/bin/env bash
# Upload the packed corpus archives to any S3-compatible bucket.
#
#   Cloudflare R2 .... free at this size (10 GB storage, egress always free)
#   AWS S3 ........... ~$0.05/month
#   Supabase Storage . free on Pro, does not fit the 1 GB free plan
#
# Usage:
#   export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=auto
#   ./scripts/upload_corpus.sh langfive-corpus \
#       https://<account-id>.r2.cloudflarestorage.com corpus/v1
#
# Then point the API at it (see .env.example):
#   LANGFIVE_CORPUS_BUCKET=langfive-corpus
#   LANGFIVE_CORPUS_PREFIX=corpus/v1
#   LANGFIVE_CORPUS_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
set -euo pipefail

BUCKET="${1:?usage: upload_corpus.sh <bucket> [endpoint-url] [prefix]}"
ENDPOINT="${2:-}"
PREFIX="${3:-}"

DATA_DIR="${LANGFIVE_DATA_DIR:-$(cd "$(dirname "$0")/.." && pwd)/data}"
SRC="$DATA_DIR/archives"

if [ ! -d "$SRC" ]; then
  echo "no archives in $SRC — run scripts/pack_corpus.sh first" >&2
  exit 1
fi

# --- free-tier circuit breaker -------------------------------------------
# R2 has no server-side spending cap: Cloudflare's budget alerts are
# explicitly "informational only. They do not pause or cap usage." So the
# ceiling has to live here, on the only side we control.
#
# Free tier is 10 GB-month of storage. Refuse to push past a fraction of it
# rather than discovering the overage on an invoice. Override deliberately:
#   LANGFIVE_CORPUS_MAX_MB=8000 ./scripts/upload_corpus.sh ...
MAX_MB="${LANGFIVE_CORPUS_MAX_MB:-2000}"
# du -cm is portable across macOS (BSD) and Linux (GNU); stat flags are not.
total_mb=$(du -cm "$SRC"/*.tar.gz 2>/dev/null | tail -1 | cut -f1)
: "${total_mb:=0}"

if [ "$total_mb" -gt "$MAX_MB" ]; then
  echo "REFUSING: archives total ${total_mb} MB, ceiling is ${MAX_MB} MB." >&2
  echo "R2 free tier is 10240 MB-month and has no hard cap on the Cloudflare" >&2
  echo "side. Raise LANGFIVE_CORPUS_MAX_MB only if you mean to." >&2
  exit 1
fi
echo "archives: ${total_mb} MB — $(( total_mb * 100 / 10240 ))% of the 10 GB free tier"

if ! command -v aws >/dev/null; then
  echo "aws CLI not found (pip install awscli)" >&2
  exit 1
fi

dest="s3://$BUCKET"
[ -n "$PREFIX" ] && dest="$dest/${PREFIX%/}"

sync_args=(--no-progress --exclude '*.tmp')
[ -n "$ENDPOINT" ] && sync_args+=(--endpoint-url "$ENDPOINT")

echo "uploading $(du -sh "$SRC" | cut -f1) -> $dest"
aws s3 sync "$SRC" "$dest" "${sync_args[@]}"

echo "done. Contents:"
list_args=()
[ -n "$ENDPOINT" ] && list_args+=(--endpoint-url "$ENDPOINT")
aws s3 ls "$dest/" "${list_args[@]}"
