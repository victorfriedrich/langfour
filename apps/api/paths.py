"""
Filesystem locations for the API's data files.

Previously every path was relative to the process's working directory
("processed/de/...", "articles", "yt_es.json"), which meant the service only
worked if you happened to launch it from inside the backend folder. In a
monorepo that assumption breaks immediately.

Everything is now resolved relative to this file, so paths hold regardless of
where the process is started from. LANGFIVE_DATA_DIR overrides the location if
the corpus is ever mounted on a volume rather than shipped in the image.
"""

import os
from pathlib import Path

# apps/api/
API_ROOT = Path(__file__).resolve().parent

# apps/api/data/  (override with LANGFIVE_DATA_DIR)
DATA_DIR = Path(os.getenv("LANGFIVE_DATA_DIR") or (API_ROOT / "data")).resolve()

# Video transcript corpus, by language code: data/processed/{de,es,fr,it}/
PROCESSED_DIR = DATA_DIR / "processed"

# Parsed articles, by language: data/articles/
ARTICLES_DIR = DATA_DIR / "articles"

DOWNLOADS_DIR = DATA_DIR / "downloaded_files"
THUMBNAILS_DIR = DATA_DIR / "youtube_thumbnails"


def data_file(name: str) -> Path:
    """Path to a loose reference dataset, e.g. data_file('yt_es.json')."""
    return DATA_DIR / name


def processed_dir(language_code: str) -> Path:
    """data/processed/<language_code>/"""
    return PROCESSED_DIR / language_code


def processed_file(language_code: str, video_id: str) -> Path:
    """data/processed/<language_code>/<video_id>_processed.json"""
    return PROCESSED_DIR / language_code / f"{video_id}_processed.json"


__all__ = [
    "API_ROOT", "DATA_DIR", "PROCESSED_DIR", "ARTICLES_DIR",
    "DOWNLOADS_DIR", "THUMBNAILS_DIR",
    "data_file", "processed_dir", "processed_file",
]
