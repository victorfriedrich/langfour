# Build context is the repository ROOT, not apps/api:
#   docker build -f apps/api/Dockerfile -t langfive-api .
#
# The root .dockerignore keeps the context small. Without it the context is
# ~2.4 GB, because the transcript corpus and the archived pre-monorepo .git
# directories both live under the root.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Application code only. The transcript corpus (~2.2 GB raw) is NOT baked in:
# corpus_sync.py streams it from object storage on startup, one gzipped
# tarball per language, ~134 MB total. Configure LANGFIVE_CORPUS_BASE_URL or
# LANGFIVE_CORPUS_BUCKET, or the recommender starts with an empty corpus.
COPY apps/api/ ./

# Fails fast rather than silently: the service refuses to start unless
# SUPABASE_SERVICE_ROLE_KEY carries the service_role claim, and refuses to
# serve if the word cache loads empty.
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
