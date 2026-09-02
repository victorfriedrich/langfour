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
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
from pathlib import Path
from typing import IO, Iterable

from paths import DATA_DIR, PROCESSED_DIR

log = logging.getLogger(__name__)

LANGUAGES = ("de", "es", "fr", "it")

# Written into each language directory once extraction finishes. Its absence
# means a previous run died midway and the directory cannot be trusted.
MARKER = ".corpus_complete"

COPY_BUFSIZE = 1024 * 1024  # 1 MB


def _is_populated(language: str) -> bool:
    return (PROCESSED_DIR / language / MARKER).exists()


def _open_stream(name: str) -> IO[bytes]:
    """Return a readable, streaming file object for one archive."""
    base_url = os.getenv("LANGFIVE_CORPUS_BASE_URL")
    if base_url:
        from urllib.request import urlopen

        url = f"{base_url.rstrip('/')}/{name}"
        log.info("corpus: fetching %s", url)
        return urlopen(url, timeout=60)  # noqa: S310 - operator-supplied URL

    bucket = os.getenv("LANGFIVE_CORPUS_BUCKET")
    if bucket:
        import boto3  # imported lazily so local dev needs no AWS SDK

        prefix = os.getenv("LANGFIVE_CORPUS_PREFIX", "").strip("/")
        key = f"{prefix}/{name}" if prefix else name
        log.info("corpus: fetching s3://%s/%s", bucket, key)
        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("LANGFIVE_CORPUS_ENDPOINT") or None,
            region_name=os.getenv("AWS_REGION", "auto"),
        )
        # StreamingBody is already a chunked reader; tarfile pulls from it.
        return s3.get_object(Bucket=bucket, Key=key)["Body"]

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


def _configured_languages() -> tuple[str, ...]:
    raw = os.getenv("LANGFIVE_CORPUS_LANGUAGES")
    if raw:
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    return LANGUAGES


__all__ = ["ensure_corpus", "ensure_language", "LANGUAGES"]
