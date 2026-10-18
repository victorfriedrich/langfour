"""The Library: episodes, movies, articles and songs a user imported to learn their words.

Each item belongs to the user who imported it and lives in `public.user_media`
(row-level security on; see docs/user-media.sql). The API writes with the
service-role client, which bypasses RLS, so every query here filters on
user_id itself. Items used to be JSON files on the API server's disk, visible
to every user and lost on each redeploy.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

from languages import require_code

MEDIA_KINDS = ("series", "movie", "article", "song", "text")

# Seconds a chunk may start before the previous one ends and still be trimmed
# to fit; the largest overlap in the Netling recordings so far is 0.37 s.
OVERLAP_TOLERANCE = 1.0

_ID = re.compile(r"[a-zA-Z0-9_-]+")

# Columns returned by the list endpoint: everything but the text and words.
SUMMARY_COLUMNS = (
    "id,kind,series,title,season,episode,artist,site,source_url,language,"
    "duration,word_count,transcription_model,timebase,imported_at"
)
DETAIL_COLUMNS = SUMMARY_COLUMNS + ",chunks"


class MediaExistsError(Exception):
    def __init__(self, media_id: str):
        super().__init__(f"Media already exists: {media_id}")
        self.media_id = media_id


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def make_media_id(series: str, season: int | None, episode: int | None) -> str:
    parts = [series]
    if season is not None:
        parts.append(f"s{season:02d}")
    if episode is not None:
        parts.append(f"e{episode:02d}")
    value = _slug("-".join(parts))
    if not value:
        raise ValueError("The series title must contain letters or numbers")
    return value


def make_text_media_id(title: str, fingerprint: str) -> str:
    """Articles and songs have no episode coordinates, and two pages can share a
    headline, so the id is the title plus a short hash of where it came from."""
    slug = _slug(title)[:60].strip("-")
    if not slug:
        raise ValueError("The title must contain letters or numbers")
    return f"{slug}-{hashlib.sha1(fingerprint.encode()).hexdigest()[:6]}"


def _normalize_chunks(chunks: list[dict]) -> tuple[list[dict], bool]:
    """Validated chunks, and whether they are timed. Subtitles and audio
    transcripts carry timestamps; articles and lyrics are plain passages. A
    transcript is one or the other, never a mix."""
    if not chunks:
        raise ValueError("At least one transcript chunk is required")
    timed = chunks[0].get("timestamp") is not None
    previous_end = 0.0
    normalized = []
    for index, chunk in enumerate(chunks):
        text = chunk["text"].strip()
        if not text:
            raise ValueError(f"Chunk {index} has no text")
        timestamp = chunk.get("timestamp")
        if (timestamp is not None) != timed:
            raise ValueError(f"Chunk {index} must {'have' if timed else 'not have'} a timestamp like the first one")
        if not timed:
            normalized.append({"timestamp": None, "text": text})
            continue
        if len(timestamp) != 2:
            raise ValueError(f"Chunk {index} must have a start and end timestamp")
        start, end = float(timestamp[0]), float(timestamp[1])
        if start < 0 or end < start:
            raise ValueError(f"Chunk {index} has an invalid timestamp")
        # Whisper segments routinely overlap their predecessor by a few hundredths
        # of a second (every Netling recording has some); trim those rather than
        # rejecting a whole episode. Out-of-order lines are still an error.
        if start < previous_end - OVERLAP_TOLERANCE:
            raise ValueError(f"Chunk {index} overlaps the previous chunk")
        start = max(start, previous_end)
        end = max(end, start)
        normalized.append({"timestamp": [start, end], "text": text})
        previous_end = end
    return normalized, timed


def prepare_media_row(payload: dict) -> dict:
    """Validate an import into a `user_media` row, without user_id or its parsed words."""
    code = require_code(payload["language"])
    kind = payload.get("media_type") or "series"
    if kind not in MEDIA_KINDS:
        raise ValueError(f"Unknown media type: {kind}")
    chunks, timed = _normalize_chunks(payload["chunks"])

    series = (payload.get("series") or "").strip() or None
    title = (payload.get("title") or "").strip() or None
    if kind == "series":
        if not series:
            raise ValueError("An episode needs its series name")
        episode = payload.get("episode")
        title = title or f"{series} - Episode {episode if episode is not None else '?'}"
        default_id = make_media_id(series, payload.get("season"), payload.get("episode"))
    else:
        if not title:
            raise ValueError("A title is required")
        default_id = make_text_media_id(title, payload.get("source_url") or "\n".join(c["text"] for c in chunks))
    media_id = payload.get("media_id") or default_id
    if not _ID.fullmatch(media_id):
        raise ValueError("media_id may contain only letters, numbers, underscores, and hyphens")

    transcript = "\n".join(chunk["text"] for chunk in chunks)
    return {
        "id": media_id,
        "language": code,
        "kind": kind,
        "title": title,
        "series": series,
        "season": payload.get("season"),
        "episode": payload.get("episode"),
        "artist": payload.get("artist"),
        "site": payload.get("site"),
        "source_url": payload.get("source_url"),
        "duration": payload.get("audio_seconds") or (chunks[-1]["timestamp"][1] if timed else None),
        "word_count": len(transcript.split()),
        "transcription_model": payload.get("model"),
        "timebase": payload.get("timebase"),
        "chunks": chunks,
        "imported_at": datetime.now(UTC).isoformat(),
    }


def to_api(row: dict) -> dict:
    """A row in the shape the web app and extension read (camelCase, as the
    file-based records were)."""
    record = {
        "id": row["id"],
        "type": row["kind"],
        "series": row.get("series"),
        "title": row["title"],
        "season": row.get("season"),
        "episode": row.get("episode"),
        "artist": row.get("artist"),
        "site": row.get("site"),
        "sourceUrl": row.get("source_url"),
        "language": row["language"],
        "duration": row.get("duration"),
        "wordCount": row.get("word_count") or 0,
        "transcriptionModel": row.get("transcription_model"),
        "timebase": row.get("timebase"),
        "importedAt": row["imported_at"],
    }
    if "chunks" in row:
        record["chunks"] = row["chunks"]
    return record


class MediaStore:
    """`public.user_media` through the service-role client: always filter on user_id."""

    def __init__(self, client):
        self.client = client

    def insert(self, user_id: str, row: dict) -> None:
        try:
            self.client.table("user_media").insert({**row, "user_id": user_id}).execute()
        except Exception as error:
            # 23505: unique_violation on (user_id, language, id).
            if getattr(error, "code", None) == "23505" or "23505" in str(error):
                raise MediaExistsError(row["id"]) from error
            raise

    def exists(self, user_id: str, language: str, media_id: str) -> bool:
        res = (self.client.table("user_media").select("id")
               .eq("user_id", user_id).eq("language", language).eq("id", media_id)
               .limit(1).execute())
        return bool(res.data)

    def list(self, user_id: str, language: str) -> list[dict]:
        res = (self.client.table("user_media").select(SUMMARY_COLUMNS)
               .eq("user_id", user_id).eq("language", language)
               .order("imported_at", desc=True).execute())
        return res.data or []

    def get(self, user_id: str, language: str, media_id: str, columns: str = DETAIL_COLUMNS) -> dict | None:
        res = (self.client.table("user_media").select(columns)
               .eq("user_id", user_id).eq("language", language).eq("id", media_id)
               .limit(1).execute())
        return res.data[0] if res.data else None


def import_media(
    store: MediaStore,
    user_id: str,
    payload: dict,
    parse_content: Callable[[list[str], str, str], list[dict]],
    group_text: Callable[[str], list[str]],
) -> dict:
    """Validate, parse and save an item to the user's Library; returns it with its text."""
    row = prepare_media_row(payload)
    # Parsing an episode takes minutes, so refuse a duplicate before doing it.
    if store.exists(user_id, row["language"], row["id"]):
        raise MediaExistsError(row["id"])
    transcript = "\n".join(chunk["text"] for chunk in row["chunks"])
    parsed = parse_content(group_text(transcript), row["id"], row["language"])
    # parse() returns every token, space and punctuation mark; the missing-words
    # list only needs each word's id once.
    row["words"] = [{"id": i} for i in dict.fromkeys(w["id"] for w in parsed if w.get("id") is not None)]
    store.insert(user_id, row)
    return to_api(row)


def list_media(store: MediaStore, user_id: str, language: str) -> list[dict]:
    return [to_api(row) for row in store.list(user_id, require_code(language))]


def get_media(store: MediaStore, user_id: str, media_id: str, language: str) -> dict:
    if not _ID.fullmatch(media_id):
        raise ValueError("Invalid media id")
    row = store.get(user_id, require_code(language), media_id)
    if row is None:
        raise FileNotFoundError(media_id)
    return to_api(row)


def get_media_words(store: MediaStore, user_id: str, media_id: str, language: str) -> list[dict]:
    """The parsed words of one of the user's items, for the missing-words list."""
    if not _ID.fullmatch(media_id):
        raise ValueError("Invalid media id")
    row = store.get(user_id, require_code(language), media_id, columns="words")
    if row is None:
        raise FileNotFoundError(media_id)
    return row.get("words") or []
