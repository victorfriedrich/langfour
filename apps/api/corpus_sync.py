"""
Fetch the transcript corpus at boot rather than shipping it in the image.

The corpus is ~2.2 GB across ~11.8k JSON files, which is too much to keep in
git and too much to bake into a container image. It compresses ~16x, so it
lives in object storage as one gzipped tarball per language (134 MB total)
and is pulled onto local disk the first time the process starts.

MEMORY PROFILE — this is the whole point of the module, so do not "simplify"
it away. Measured on the Spanish archive (118 MB compressed, 1.99 GB and
10,652 files decompressed):

    streaming, as written here .................  20 MB peak RSS
    io.BytesIO(body.read()) + getmembers() .....  130 MB peak RSS

Three things keep it flat, and all three matter:

  * Mode "r|gz", not "r:gz". The pipe selects the streaming reader, which
    decodes one block at a time and never needs to seek. "r:gz" against a
    non-seekable HTTP or S3 body is what pushes people into reading the whole
    response into a BytesIO first, which is the 130 MB column above.
  * Members are iterated with `for member in tar`. getmembers() and getnames()
    materialise a TarInfo for all 10,652 entries at once; the loop holds one.
  * Files are copied out with copyfileobj and an explicit 1 MB buffer, never
    .read() in one shot — individual transcripts run to several hundred KB and
    the largest single member is ~7 MB.

The cost of the streaming approach is that the archive can only be read
forward, once. That is exactly the access pattern here, so it costs nothing.

Configuration (first match wins):

  LANGFIVE_CORPUS_BASE_URL   https://<host>/<prefix>   public or presigned
  LANGFIVE_CORPUS_BUCKET     bucket name, S3-compatible (R2, S3, Supabase
                             Storage); with LANGFIVE_CORPUS_ENDPOINT and the
                             usual AWS_* credential vars

If neither is set the corpus is assumed to be on disk already, which is the
normal case in local development.

INCOMING — transcripts the API's own ingest worker makes (ingest_worker.py)
would die with the container's disk, so each one is also uploaded on its own,
gzipped, to <prefix>/incoming/<lang>/<id>_processed.json.gz. Boot pulls them
in after the tarball. That needs the bucket configuration (listing is an S3
call) and, for the upload only, a read-write token in
LANGFIVE_CORPUS_WRITE_ACCESS_KEY_ID / LANGFIVE_CORPUS_WRITE_SECRET_ACCESS_KEY;
the AWS_* token stays read-only. Repacking the tarballs from a disk that has
pulled incoming/ folds them in.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import tarfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import IO

from paths import DATA_DIR, PROCESSED_DIR, processed_dir, processed_file

log = logging.getLogger(__name__)

LANGUAGES = ("de", "es", "fr", "it")

# Written into each language directory once extraction finishes. Its absence
# means a previous run died midway and the directory cannot be trusted.
MARKER = ".corpus_complete"

COPY_BUFSIZE = 1024 * 1024  # 1 MB

# incoming/ is thousands of ~17 KB objects, so pulling it is bound by request
# latency, not bandwidth. Measured against R2: 8 workers ~32 objects/s, 32
# workers ~64/s, 64 workers no better. botocore keeps 10 connections per client
# by default, so the client pool is sized to match or the extra workers queue.
INCOMING_WORKERS = 32


def _is_populated(language: str) -> bool:
    return (PROCESSED_DIR / language / MARKER).exists()


def _key(name: str) -> str:
    prefix = os.getenv("LANGFIVE_CORPUS_PREFIX", "").strip("/")
    return f"{prefix}/{name}" if prefix else name


def _s3(write: bool = False):
    import boto3  # imported lazily so local dev needs no AWS SDK
    from botocore.config import Config

    creds = {}
    if write:
        key_id = os.getenv("LANGFIVE_CORPUS_WRITE_ACCESS_KEY_ID")
        secret = os.getenv("LANGFIVE_CORPUS_WRITE_SECRET_ACCESS_KEY")
        if not (key_id and secret):
            raise RuntimeError("uploading needs LANGFIVE_CORPUS_WRITE_ACCESS_KEY_ID "
                               "and LANGFIVE_CORPUS_WRITE_SECRET_ACCESS_KEY")
        creds = {"aws_access_key_id": key_id, "aws_secret_access_key": secret}
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("LANGFIVE_CORPUS_ENDPOINT") or None,
        region_name=os.getenv("AWS_REGION", "auto"),
        config=Config(max_pool_connections=INCOMING_WORKERS),
        **creds,
    )


def _open_stream(name: str) -> IO[bytes]:
    """Return a readable, streaming file object for one archive."""
    base_url = os.getenv("LANGFIVE_CORPUS_BASE_URL")
    if base_url:
        from urllib.request import urlopen

        url = f"{base_url.rstrip('/')}/{name}"
        log.info("corpus: fetching %s", url)
        return urlopen(url, timeout=60)

    bucket = os.getenv("LANGFIVE_CORPUS_BUCKET")
    if bucket:
        key = _key(name)
        log.info("corpus: fetching s3://%s/%s", bucket, key)
        # StreamingBody is already a chunked reader; tarfile pulls from it.
        return _s3().get_object(Bucket=bucket, Key=key)["Body"]

    raise RuntimeError(
        "No corpus source configured. Set LANGFIVE_CORPUS_BASE_URL or "
        "LANGFIVE_CORPUS_BUCKET, or provide data/processed/ on disk."
    )


def _safe_members(tar: tarfile.TarFile, language: str) -> Iterable[tarfile.TarInfo]:
    """Yield members, refusing anything that would escape the target dir.

    The archive is remote input, so absolute paths, '..' traversal, symlinks
    and device nodes are all rejected rather than trusted.
    """
    expected = f"processed/{language}/"
    for member in tar:
        name = member.name
        if name.startswith("/") or ".." in Path(name).parts:
            log.warning("corpus: skipping suspicious member %r", name)
            continue
        if not (name == expected.rstrip("/") or name.startswith(expected)):
            log.warning("corpus: skipping out-of-tree member %r", name)
            continue
        if member.issym() or member.islnk() or member.isdev():
            log.warning("corpus: skipping non-regular member %r", name)
            continue
        if Path(name).name.startswith("._"):
            # macOS AppleDouble metadata, packed by a Mac tar. Not JSON: each
            # one only costs a write here and an "Error loading" line later.
            continue
        yield member


def _extract(stream: IO[bytes], language: str) -> int:
    count = 0
    # "r|gz" = streaming. See the module docstring before changing this.
    with tarfile.open(fileobj=stream, mode="r|gz") as tar:
        for member in _safe_members(tar, language):
            target = DATA_DIR / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            with src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, COPY_BUFSIZE)
            count += 1
    return count


def ensure_language(language: str, *, force: bool = False) -> bool:
    """Make data/processed/<language>/ available. Returns True if it fetched."""
    if not force and _is_populated(language):
        log.info("corpus: %s already present, skipping", language)
        return False

    target_dir = PROCESSED_DIR / language
    marker = target_dir / MARKER
    if marker.exists():
        marker.unlink()

    stream = _open_stream(f"{language}.tar.gz")
    try:
        count = _extract(stream, language)
    finally:
        close = getattr(stream, "close", None)
        if close:
            close()

    target_dir.mkdir(parents=True, exist_ok=True)
    marker.touch()
    log.info("corpus: %s ready (%d files)", language, count)
    return True


# Remote input like the tarball: only a bare transcript name becomes a path.
INCOMING_NAME = re.compile(r"^([A-Za-z0-9_-]+)_processed\.json\.gz$")


def upload_transcript(language: str, video_id: str) -> None:
    """Copy one finished transcript to incoming/, so it outlives this disk."""
    bucket = os.getenv("LANGFIVE_CORPUS_BUCKET")
    if not bucket:
        raise RuntimeError("uploading needs LANGFIVE_CORPUS_BUCKET")
    body = gzip.compress(processed_file(language, video_id).read_bytes())
    _s3(write=True).put_object(Bucket=bucket, Key=_key(f"incoming/{language}/{video_id}_processed.json.gz"),
                               Body=body, ContentType="application/json", ContentEncoding="gzip")


def pull_incoming(language: str) -> int:
    """Fetch the incoming/ transcripts this disk lacks. Returns how many.

    One small object each (~17 KB gzipped), so they come INCOMING_WORKERS at a
    time; the tarball's single stream is what has to stay sequential."""
    bucket = os.environ["LANGFIVE_CORPUS_BUCKET"]
    s3 = _s3()
    prefix = _key(f"incoming/{language}/")
    wanted = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            match = INCOMING_NAME.match(obj["Key"][len(prefix):])
            if match and not processed_file(language, match.group(1)).exists():
                wanted.append((obj["Key"], match.group(1)))

    def fetch(item: tuple[str, str]) -> None:
        key, video_id = item
        target = processed_file(language, video_id)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(gzip.decompress(s3.get_object(Bucket=bucket, Key=key)["Body"].read()))
        tmp.replace(target)

    processed_dir(language).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(INCOMING_WORKERS) as pool:
        list(pool.map(fetch, wanted))
    log.info("corpus: %s pulled %d incoming transcripts", language, len(wanted))
    return len(wanted)


def ensure_corpus(languages: Iterable[str] | None = None) -> None:
    """Fetch every configured language, sequentially.

    Sequential is deliberate: parallel downloads would multiply peak memory
    and saturate the container's network for no gain on a cold start.

    A failure is logged, not raised. The service starts either way and the
    recommender simply has less to work with -- a partial corpus is better
    than a boot loop.
    """
    wanted = tuple(languages or _configured_languages())
    if not wanted:
        return

    if not (os.getenv("LANGFIVE_CORPUS_BASE_URL") or os.getenv("LANGFIVE_CORPUS_BUCKET")):
        missing = [lang for lang in wanted if not (PROCESSED_DIR / lang).is_dir()]
        if missing:
            log.warning(
                "corpus: no source configured and %s missing from %s",
                ", ".join(missing), PROCESSED_DIR,
            )
        return

    for language in wanted:
        try:
            ensure_language(language)
        except Exception:
            log.exception("corpus: failed to fetch %s", language)
        if os.getenv("LANGFIVE_CORPUS_BUCKET"):
            try:
                pull_incoming(language)
            except Exception:
                log.exception("corpus: failed to pull incoming %s", language)


def _configured_languages() -> tuple[str, ...]:
    raw = os.getenv("LANGFIVE_CORPUS_LANGUAGES")
    if raw:
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    return LANGUAGES


__all__ = ["LANGUAGES", "ensure_corpus", "ensure_language", "pull_incoming", "upload_transcript"]
