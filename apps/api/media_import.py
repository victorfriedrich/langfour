"""Import and persist transcripts for episodes and other long-form media."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from paths import PROCESSED_DIR


from languages import require_code


def make_media_id(series: str, season: int | None, episode: int | None) -> str:
    parts = [series]
    if season is not None:
        parts.append(f"s{season:02d}")
    if episode is not None:
        parts.append(f"e{episode:02d}")
    value = unicodedata.normalize("NFKD", "-".join(parts)).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value:
        raise ValueError("The series title must contain letters or numbers")
    return value


def import_media(
    payload: dict,
    parse_content: Callable[[list[str], str, str], list[dict]],
    group_text: Callable[[str], list[str]],
    media_dir: str | Path = "media",
    processed_dir: str | Path = PROCESSED_DIR,
) -> dict:
    """Validate an episode transcript, parse its words, and save both representations."""
    code = require_code(payload["language"])
    chunks = payload["chunks"]
    if not chunks:
        raise ValueError("At least one transcript chunk is required")

    previous_end = 0.0
    normalized_chunks = []
    for index, chunk in enumerate(chunks):
        timestamp = chunk["timestamp"]
        if len(timestamp) != 2:
            raise ValueError(f"Chunk {index} must have a start and end timestamp")
        start, end = float(timestamp[0]), float(timestamp[1])
        if start < 0 or end < start:
            raise ValueError(f"Chunk {index} has an invalid timestamp")
        if start < previous_end:
            raise ValueError(f"Chunk {index} overlaps the previous chunk")
        text = chunk["text"].strip()
        if not text:
            raise ValueError(f"Chunk {index} has no text")
        normalized_chunks.append({"timestamp": [start, end], "text": text})
        previous_end = end

    media_id = payload.get("media_id") or make_media_id(
        payload["series"], payload.get("season"), payload.get("episode")
    )
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", media_id):
        raise ValueError("media_id may contain only letters, numbers, underscores, and hyphens")

    media_path = Path(media_dir) / code / f"{media_id}.json"
    processed_path = Path(processed_dir) / code / f"{media_id}_processed.json"
    if media_path.exists() or processed_path.exists():
        raise FileExistsError(f"Media already exists: {media_id}")

    transcript = "\n".join(chunk["text"] for chunk in normalized_chunks)
    content = parse_content(group_text(transcript), media_id, code)
    imported_at = datetime.now(timezone.utc).isoformat()
    duration = payload.get("audio_seconds") or normalized_chunks[-1]["timestamp"][1]
    title = payload.get("title") or f"{payload['series']} - Episode {payload.get('episode', '?')}"

    media_record = {
        "id": media_id,
        "type": payload.get("media_type", "series"),
        "series": payload["series"],
        "title": title,
        "season": payload.get("season"),
        "episode": payload.get("episode"),
        "language": code,
        "duration": duration,
        "transcriptionModel": payload.get("model"),
        "timebase": payload.get("timebase"),
        "importedAt": imported_at,
        "chunks": normalized_chunks,
    }
    processed_record = {
        "title": title,
        "id": media_id,
        "tags": ["Imported media", payload["series"]],
        "creator": payload["series"],
        "views": 0,
        "length": duration,
        "content": content,
        "dateAdded": imported_at,
        "category": "Imported media",
        "media": {"type": media_record["type"], "season": payload.get("season"), "episode": payload.get("episode")},
    }

    media_path.parent.mkdir(parents=True, exist_ok=True)
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_text(json.dumps(media_record, ensure_ascii=False, indent=2), encoding="utf-8")
    processed_path.write_text(json.dumps(processed_record, ensure_ascii=False, indent=2), encoding="utf-8")
    return media_record


def list_media(language: str, media_dir: str | Path = "media") -> list[dict]:
    code = require_code(language)
    records = []
    for path in (Path(media_dir) / code).glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("chunks", None)
        records.append(record)
    return sorted(records, key=lambda item: (item["series"], item.get("season") or 0, item.get("episode") or 0))


def get_media(media_id: str, language: str, media_dir: str | Path = "media") -> dict:
    code = require_code(language)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", media_id):
        raise ValueError("Invalid media id")
    path = Path(media_dir) / code / f"{media_id}.json"
    if not path.exists():
        raise FileNotFoundError(media_id)
    return json.loads(path.read_text(encoding="utf-8"))
