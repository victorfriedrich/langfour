#!/usr/bin/env python3
"""
ytpipeline.py - build a language-filtered list of YouTube videos.

  discovery
    harvest   Common Crawl URL index -> channel ids      free
    enrich    channels.list          -> metadata         1 unit / 50 channels
    detect    channel description    -> language         free, local
    videos    uploads + videos.list  -> per-video data   2 units / channel
  selection
    classify  cached titles -> LLM verdict per channel   MODEL_FAST, cheap
    expand    search.list top-viewed, gated channels     101 units / channel
    select    gates + per-video ranking -> video_queue   free
  ingestion
    ingest.py drains video_queue (Supabase) into transcripts

One SQLite file, one row per channel, so each stage is resumable and nothing
already paid for is fetched twice. Selection reads only cached rows, so a
threshold can be re-tuned for free; the two stages that spend (classify,
expand) run only on channels that already cleared every cheaper gate.

The stages are deliberately language-agnostic. `videos` is the only expensive
one, and channels that are ambiguous for Spanish are the same channels that are
ambiguous for French -- caching per channel rather than per language run is
what makes the second language nearly free.

    python ytpipeline.py harvest
    python ytpipeline.py enrich --budget 9000
    python ytpipeline.py detect
    python ytpipeline.py videos --lang es --min-subs 100000 --budget 9000
    python ytpipeline.py classify --lang es
    python ytpipeline.py expand --lang es --budget 9000
    python ytpipeline.py select --lang es --push
"""

from __future__ import annotations

import argparse
import atexit
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import fcntl
import gzip
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from paths import API_ROOT, DATA_DIR

DB = DATA_DIR / "seeds" / "channels.sqlite"
BULK = "https://data.commoncrawl.org"
UA = "Mozilla/5.0 (compatible; langfive-research/1.0)"
UC_RE = re.compile(r"/channel/(UC[A-Za-z0-9_-]{22})")
PREFIX = "com,youtube)/channel/"

# Crawls are published roughly monthly; this is a static list so a harvest never
# depends on index.commoncrawl.org, which throttles hard and is a different
# service from the bulk host below. `--crawls` overrides it.
CRAWLS = [f"CC-MAIN-{c}" for c in (
    "2026-34 2026-30 2026-25 2026-21 2026-17 2026-12 2026-08 2026-04 "
    "2025-51 2025-47 2025-43 2025-38 2025-33 2025-30 2025-26 2025-21 "
    "2025-18 2025-13 2025-08 2025-05 2024-51 2024-46 2024-42 2024-38 "
    "2024-33 2024-30 2024-26 2024-22 2024-18 2024-10 2023-50 2023-40 "
    "2023-23 2023-14 2023-06 2022-49 2022-40 2022-33 2022-27 2022-21 2022-05"
).split()]

# Video selection, carried over from the Selenium script it replaced so results
# stay comparable: prefer short, prefer viewed, never longer than 33 minutes.
MAX_MINUTES, TOP_N, VIEW_BIAS = 33, 15, 0.9
MUSIC_CATEGORY = "10"
KEY_RE = re.compile(r"([?&]key=)[^&\s\"'<>]+")

_LOCK_HANDLE = None            # open lock file; closing it releases the flock

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id  TEXT PRIMARY KEY,
    crawl_count INTEGER DEFAULT 0,      -- distinct crawls linking it; informational
    first_crawl TEXT, last_crawl TEXT,
    title TEXT, description TEXT, custom_url TEXT, country TEXT,
    subscribers INTEGER,                -- NULL when hidden, never 0
    views INTEGER, video_count INTEGER,
    topics TEXT, published_at TEXT, uploads TEXT, raw TEXT,
    lang TEXT, lang_conf REAL,          -- from detect
    enriched_at TEXT, videos_at TEXT,   -- NULL = stage not run; also the TTL
    audio_lang TEXT, music_share REAL, note TEXT,
    expanded_at TEXT,                   -- search.list top-viewed pull done
    classified_at TEXT, sensitivity REAL, intellectuality REAL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL,
    title TEXT, description TEXT, published_at TEXT,
    views INTEGER, likes INTEGER, comments INTEGER,
    duration_s INTEGER, category_id TEXT, audio_lang TEXT,
    caption TEXT,                       -- 'true' = usable without transcription
    live TEXT,
    source TEXT NOT NULL DEFAULT 'uploads'  -- 'uploads' sample | 'search' top-viewed
);

CREATE TABLE IF NOT EXISTS done (stage TEXT, key TEXT, at TEXT, PRIMARY KEY (stage, key));
"""

# Created after the ALTER pass, not inside SCHEMA: an index may name a column
# that only exists once connect() has added it, and SCHEMA runs first.
INDEXES = """
CREATE INDEX IF NOT EXISTS ix_lang ON channels(lang, subscribers DESC);
CREATE INDEX IF NOT EXISTS ix_subs ON channels(subscribers DESC);
CREATE INDEX IF NOT EXISTS ix_vchan ON videos(channel_id);
-- Selection filters on the *effective* language, COALESCE(audio_lang, lang),
-- which ix_lang cannot serve: a COALESCE over two columns is not a column.
-- Indexing the expression lets CHANNEL_STATS start from the few thousand
-- channels of one language instead of scanning every row in videos.
CREATE INDEX IF NOT EXISTS ix_effective_lang
    ON channels(COALESCE(audio_lang, lang), videos_at);
"""

# Columns added after the store was first built. connect() adds any that are
# missing, so an existing multi-GB store upgrades in place on first use.
ADDED_COLUMNS = {
    "channels": ["expanded_at TEXT", "classified_at TEXT", "sensitivity REAL",
                 "intellectuality REAL"],
    "videos": ["source TEXT NOT NULL DEFAULT 'uploads'"],
}

# The one place the videos column list is spelled. It used to live in four --
# SCHEMA, ADDED_COLUMNS, a bare `14`, and the tests -- and the INSERTs were
# positional, so a column added in the middle of SCHEMA would land in the
# middle for a fresh store and at the end for an ALTER-upgraded one, and every
# value would then be written one column off with no error at all. Naming the
# columns removes that failure mode outright; test_video_cols_match_the_schema
# keeps this tuple honest.
VIDEO_COLS = ("video_id", "channel_id", "title", "description", "published_at",
              "views", "likes", "comments", "duration_s", "category_id",
              "audio_lang", "caption", "live", "source")
VIDEO_COLUMNS = len(VIDEO_COLS)
INSERT_VIDEO = ("INSERT OR {} INTO videos (" + ", ".join(VIDEO_COLS) + ") "
                "VALUES (" + ", ".join("?" * VIDEO_COLUMNS) + ")")


# ─────────────────────────────────────────────────────────────── store ──

def connect(path: Path = DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=60000")   # detect can read while enrich writes
    db.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        have = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for column in columns:
            if column.split()[0] not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
    db.executescript(INDEXES)
    db.commit()
    return db


def lock(path: Path) -> None:
    """One writer at a time. Two runs would build the same worklist and pay twice.

    flock, not a pid file: the kernel drops the lock on any exit, including
    kill -9, so there is no stale file to detect and no recycled pid to
    misread. The handle is kept alive deliberately -- closing it unlocks."""
    global _LOCK_HANDLE
    f = path.with_suffix(".lock")
    _LOCK_HANDLE = f.open("w")
    try:
        fcntl.flock(_LOCK_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(f"another run holds {f}; wait for it to finish")
    atexit.register(lambda: f.unlink(missing_ok=True))


def redact(text: str) -> str:
    """An HttpError renders as the full request URL, key included."""
    return KEY_RE.sub(r"\1REDACTED", text)


# ──────────────────────────────────────────────────────────────── http ──

def fetch(url: str, rng: Optional[tuple[int, int]] = None, tries: int = 4) -> Optional[bytes]:
    """Bytes, or None for a genuine 404. Anything else retries then raises."""
    headers = {"User-Agent": UA}
    if rng:
        headers["Range"] = f"bytes={rng[0]}-{rng[1]}"
    for attempt in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = f"HTTP {e.code}"
        except Exception as e:
            last = type(e).__name__
        time.sleep(3 * 2 ** attempt)
    raise RuntimeError(f"{url.rsplit('/', 1)[-1]}: {last}")


def content_length(url: str, tries: int = 4) -> Optional[int]:
    """Remote size, or None for a genuine 404, with the same retry policy as fetch."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return int(response.headers["Content-Length"])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = f"HTTP {exc.code}"
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(3 * 2 ** attempt)
    raise RuntimeError(f"{url.rsplit('/', 1)[-1]}: {last}")


# ───────────────────────────────────────────────────── stage: harvest ──

def blocks_for(crawl: str) -> Optional[list[tuple[str, int, int]]]:
    """cluster.idx entries covering youtube.com/channel/.

    cluster.idx is ~100 MB and sorted, so it is binary-searched with small range
    reads. Returns None when the crawl has not been published on the bulk host.
    """
    url = f"{BULK}/cc-index/collections/{crawl}/indexes/cluster.idx"
    size = content_length(url)
    if size is None:
        return None

    def key_at(pos: int) -> str:
        chunk = fetch(url, (pos, min(pos + 8192, size - 1)))
        if not chunk:
            raise RuntimeError(f"{crawl}: empty cluster.idx range response")
        if pos == 0:
            line = chunk.split(b"\n", 1)[0]
        else:
            parts = chunk.split(b"\n", 2)
            # A missing complete line is beyond the searchable data, not an
            # empty key. U+10FFFF deliberately sorts above every index key.
            if len(parts) < 2 or not parts[1]:
                return "\U0010ffff"
            line = parts[1]
        return line.decode("utf-8", "ignore").split(" ", 1)[0]

    lo, hi = 0, size - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if key_at(mid) < PREFIX:
            lo = mid + 1
        else:
            hi = mid
    start = max(0, lo - 65536)
    out, prev = [], None
    pending = b""
    discard_partial = start > 0
    pos = start
    finished = False
    while pos < size and not finished:
        end = min(pos + 524288 - 1, size - 1)
        chunk = fetch(url, (pos, end))
        if not chunk:
            raise RuntimeError(f"{crawl}: empty cluster.idx range response")
        data = pending + chunk
        lines = data.split(b"\n")
        pending = lines.pop()
        if discard_partial:
            lines = lines[1:]
            discard_partial = False
        for raw_bytes in lines:
            raw = raw_bytes.decode("utf-8", "ignore")
            parts = raw.split("\t")
            if len(parts) < 4:
                continue
            try:
                entry = (parts[1], int(parts[2]), int(parts[3]))
            except ValueError:
                continue
            key = parts[0].split(" ", 1)[0]
            if key < PREFIX:
                prev = entry                  # block straddling the boundary
            elif key.startswith(PREFIX):
                if prev:
                    out.append(prev)
                    prev = None
                out.append(entry)
            else:
                finished = True
                break
        pos = end + 1

    # cluster.idx normally ends with a newline. Parse the final record too so
    # an unusual but valid response cannot truncate the matching range.
    if pending and not finished:
        raw = pending.decode("utf-8", "ignore")
        parts = raw.split("\t")
        if len(parts) >= 4:
            try:
                entry = (parts[1], int(parts[2]), int(parts[3]))
            except ValueError:
                entry = None
            key = parts[0].split(" ", 1)[0]
            if entry and key < PREFIX:
                prev = entry
            elif entry and key.startswith(PREFIX):
                if prev:
                    out.append(prev)
                out.append(entry)
    return out or ([prev] if prev else [])


def harvest(db: sqlite3.Connection, crawls: Sequence[str]) -> None:
    done = {k for (k,) in db.execute("SELECT key FROM done WHERE stage='harvest'")}
    for i, crawl in enumerate(crawls, 1):
        if crawl in done:
            continue
        # Collect the whole crawl before writing. Counting per block is what
        # inflated crawl_count previously: a channel in three blocks counted
        # three times, because the guard compared against the newest crawl seen
        # rather than the one being ingested.
        blocks = blocks_for(crawl)
        if blocks is None:
            print(f"[{i}/{len(crawls)}] {crawl}: not published; will retry", flush=True)
            continue
        ids: set[str] = set()
        failed = None
        for shard, off, length in blocks:
            raw = fetch(f"{BULK}/cc-index/collections/{crawl}/indexes/{shard}",
                        (off, off + length - 1))
            if not raw:
                failed = f"{shard}: missing block"
                break
            try:
                text = gzip.decompress(raw).decode("utf-8", "ignore")
            except (OSError, EOFError):
                failed = f"{shard}: invalid gzip block"
                break
            ids.update(m.group(1) for m in UC_RE.finditer(text))
            time.sleep(0.4)
        if failed:
            print(f"[{i}/{len(crawls)}] {crawl}: {failed}; will retry", flush=True)
            continue
        db.executemany("""
            INSERT INTO channels (channel_id, crawl_count, first_crawl, last_crawl)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                crawl_count = crawl_count + 1,
                first_crawl = MIN(first_crawl, excluded.first_crawl),
                last_crawl  = MAX(last_crawl,  excluded.last_crawl)
        """, [(c, crawl, crawl) for c in ids])
        db.execute("INSERT INTO done VALUES ('harvest', ?, datetime('now'))", (crawl,))
        db.commit()
        total = db.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        print(f"[{i}/{len(crawls)}] {crawl}: +{len(ids):,} -> {total:,} unique", flush=True)


# ───────────────────────────────────────────────────────── youtube api ──

class YouTube:
    """channels.list and videos.list cost 1 unit per call regardless of how many
    parts or ids are asked for, so both are always batched at 50 and always ask
    for everything. A narrow request costs the same and forces a re-fetch."""

    CHANNEL_PARTS = "snippet,statistics,contentDetails,topicDetails,status"
    VIDEO_PARTS = "snippet,statistics,contentDetails"

    def __init__(self, budget: int):
        from dotenv import load_dotenv
        load_dotenv(API_ROOT / ".env")     # find_dotenv() only walks up from cwd
        key = os.getenv("YOUTUBE_API_KEY")
        if not key:
            sys.exit(f"set YOUTUBE_API_KEY in {API_ROOT / '.env'}")
        from googleapiclient.discovery import build
        self.api = build("youtube", "v3", developerKey=key, cache_discovery=False)
        self.used, self.budget = 0, budget

    def _call(self, resource, cost: int = 1, **kw) -> list[dict]:
        """Budget / Gone / RuntimeError -- decided here, where the typed
        HttpError still exists. Callers used to re-parse the rendered string to
        recover what this method had just thrown away."""
        from googleapiclient.errors import HttpError
        if self.used + cost > self.budget:
            raise Budget("local budget reached")
        self.used += cost
        for attempt in range(3):
            try:
                return resource().list(**kw).execute().get("items", [])
            except HttpError as exc:
                reason = error_reason(exc)
                if reason in QUOTA_REASONS:
                    raise Budget("daily quota exhausted") from exc
                # 404/410 is settled; a permanent 403 needs the reason string.
                # Either way there is nothing to retry -- and str(exc) renders
                # the request URL, key included, so it must be redacted.
                if exc.status_code in (404, 410) or reason in PERMANENT_REASONS:
                    raise Gone(redact(str(exc))) from exc
                # userRateLimitExceeded is a per-second throttle, not the daily
                # cap: back off and continue rather than ending the run.
                if attempt == 2:
                    raise RuntimeError(redact(str(exc))) from exc
            except Exception as exc:
                if attempt == 2:
                    raise RuntimeError(redact(str(exc))) from exc
            time.sleep(2 ** attempt)
        return []

    def channels(self, ids: Sequence[str]) -> list[dict]:
        return self._call(self.api.channels, part=self.CHANNEL_PARTS,
                          id=",".join(ids), maxResults=50)

    def playlist(self, playlist_id: str, n: int) -> list[str]:
        if not 1 <= n <= 50:
            raise ValueError("playlist sample must be from 1 to 50")
        items = self._call(self.api.playlistItems, part="contentDetails",
                           playlistId=playlist_id, maxResults=n)
        return [i["contentDetails"]["videoId"] for i in items]

    def videos(self, ids: Sequence[str]) -> list[dict]:
        return self._call(self.api.videos, part=self.VIDEO_PARTS,
                          id=",".join(ids), maxResults=50)

    def search(self, channel_id: str, n: int = 50) -> list[str]:
        """A channel's most-viewed videos. 100 units -- fifty playlist pages --
        so only spent on channels that cleared every other gate. The uploads
        sample is recency-ordered and for a daily uploader covers days, not
        the channel's best work. videoDuration=medium (4-20 min) sits inside
        the 8-25 min preference and keeps shorts and streams out of the fifty."""
        items = self._call(self.api.search, cost=100, part="id", channelId=channel_id,
                           type="video", order="viewCount", videoDuration="medium",
                           maxResults=n)
        return [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]


class Budget(RuntimeError):
    """The day's quota, or this run's --budget, is spent."""


class Gone(RuntimeError):
    """Permanently unavailable: deleted, terminated, or private. Retrying buys
    the same answer again -- for search.list, at 100 units a time."""


# 403 is not one thing. quotaExceeded means the day is over; the throttle means
# slow down; the rest mean this resource is not coming back. status_code cannot
# tell them apart, so the reason string does.
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})
PERMANENT_REASONS = frozenset({
    "forbidden", "channelClosed", "channelSuspended", "channelNotFound",
    "playlistItemsNotAccessible", "playlistNotFound", "videoNotFound",
})


def error_reason(exc: "HttpError") -> str:
    """The API's own reason code, e.g. 'quotaExceeded'.

    Read from the raw body, not from str(exc). On the pinned client
    (google-api-python-client 2.149) the rendered text is only the API's
    *message* -- 'you have exceeded your quota' -- so matching the reason code
    against it is luck, and error_details comes back empty when a body carries
    no top-level message. The body always has the code."""
    try:
        errors = json.loads(exc.content or b"{}").get("error", {}).get("errors") or []
        if errors and isinstance(errors[0], dict) and errors[0].get("reason"):
            return errors[0]["reason"]
    except Exception:                          # noqa: BLE001 - best effort only
        pass
    try:
        details = exc.error_details or []
        if details and isinstance(details[0], dict):
            return details[0].get("reason") or ""
    except Exception:                          # noqa: BLE001
        pass
    text = str(exc)
    return next((r for r in QUOTA_REASONS | PERMANENT_REASONS if r in text), "")


def batched(seq: Sequence[Any], n: int = 50) -> Iterable[list]:
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ────────────────────────────────────────────────────── stage: enrich ──

def enrich(db: sqlite3.Connection, yt: YouTube, stale_days: int) -> None:
    rows = db.execute("""SELECT channel_id FROM channels
                         WHERE enriched_at IS NULL
                            OR julianday('now') - julianday(enriched_at) > ?""",
                      (stale_days,)).fetchall()
    todo = [r[0] for r in rows]
    print(f"{todo and len(todo) or 0:,} channels to enrich "
          f"({-(-len(todo) // 50):,} units)", flush=True)
    for n, chunk in enumerate(batched(todo), 1):
        try:
            items = yt.channels(chunk)
        except Budget as why:
            print(f"stopped at {n * 50:,}: {why or 'local budget reached'}"); break
        except RuntimeError as exc:
            print(f"  batch {n} failed: {str(exc)[:120]}"); continue
        db.executemany("""
            UPDATE channels SET title=?, description=?, custom_url=?, country=?,
                subscribers=?, views=?, video_count=?, topics=?, published_at=?,
                uploads=?, raw=?, enriched_at=datetime('now'), lang=NULL, lang_conf=NULL,
                note=CASE WHEN note='not_returned' THEN NULL ELSE note END
            WHERE channel_id=?""", [channel_row(i) for i in items])
        # Absent from the response = deleted or terminated. Stamped so it is
        # skipped until it goes stale, not retried on every run.
        found = {i["id"] for i in items}
        db.executemany("""UPDATE channels SET enriched_at=datetime('now'),
                          note='not_returned' WHERE channel_id=?""",
                       [(c,) for c in chunk if c not in found])
        db.commit()
        if n % 50 == 0:
            print(f"  {n * 50:,}/{len(todo):,}  [{yt.used}/{yt.budget} units]", flush=True)


def channel_row(item: dict) -> tuple:
    sn, st = item.get("snippet", {}), item.get("statistics", {})
    hidden = st.get("hiddenSubscriberCount")
    return (
        sn.get("title"), sn.get("description"), sn.get("customUrl"), sn.get("country"),
        None if hidden else int(st.get("subscriberCount") or 0),   # hidden != 0
        int(st.get("viewCount") or 0), int(st.get("videoCount") or 0),
        json.dumps([u.rsplit("/", 1)[-1]
                    for u in item.get("topicDetails", {}).get("topicCategories", [])]),
        sn.get("publishedAt"),
        item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        json.dumps(item, separators=(",", ":")),
        item["id"],
    )


# ────────────────────────────────────────────────────── stage: detect ──

# Broad on purpose: restricting to the target languages would force an English
# channel into one of them instead of excluding it.
DETECT_LANGS = ("ENGLISH SPANISH FRENCH GERMAN ITALIAN PORTUGUESE DUTCH POLISH "
                "RUSSIAN UKRAINIAN TURKISH ARABIC JAPANESE KOREAN CHINESE HINDI "
                "INDONESIAN VIETNAMESE THAI SWEDISH DANISH BOKMAL FINNISH CZECH "
                "GREEK HUNGARIAN ROMANIAN CATALAN").split()
NOISE = re.compile(r"https?://\S+|www\.\S+|\S+\.(?:com|net|org|io|ly|me|tv)/\S*"
                   r"|[@#]\w+|[|•·▶→←/\\_*=+~`\[\](){}<>]+")
MIN_CHARS, MIN_CONF = 25, 0.60
DETECT_BATCH_SIZE = 1_000
MIN_AUDIO_LANG_SAMPLES = 3
CLASSIFY_WORKERS = 8           # LLM calls in flight; the stage is pure waiting


def clean(text: str) -> str:
    """Links and handles are language-neutral but dominate a short description --
    one French channel was read as Dutch purely because of a linktr.ee URL."""
    return re.sub(r"\s+", " ", NOISE.sub(" ", text or "")).strip()


def detect(db: sqlite3.Connection, batch_size: int = DETECT_BATCH_SIZE) -> None:
    from lingua import Language, LanguageDetectorBuilder
    det = (LanguageDetectorBuilder
           .from_languages(*[getattr(Language, n) for n in DETECT_LANGS])
           .with_preloaded_language_models().build())
    total = db.execute("""SELECT COUNT(*) FROM channels
                          WHERE enriched_at IS NOT NULL AND lang_conf IS NULL""").fetchone()[0]
    print(f"detecting over {total:,} channels", flush=True)
    processed = named = last_rowid = 0
    while True:
        rows = db.execute("""SELECT rowid, channel_id, description, title
                             FROM channels
                             WHERE rowid > ? AND enriched_at IS NOT NULL
                               AND lang_conf IS NULL
                             ORDER BY rowid LIMIT ?""",
                          (last_rowid, batch_size)).fetchall()
        if not rows:
            break
        out = []
        for _, cid, desc, title in rows:
            lang, conf = None, 0.0
            for text in (clean(desc), clean(title)):
                if len(text) < MIN_CHARS:
                    continue
                vals = det.compute_language_confidence_values(text)
                if vals:
                    conf = vals[0].value
                    # Abstain rather than guess: a wrong label silently poisons a
                    # pool, a missing one just leaves the channel to the videos stage.
                    lang = (vals[0].language.iso_code_639_1.name.lower()
                            if conf >= MIN_CONF else None)
                break
            out.append((lang, conf, cid))
        db.executemany("UPDATE channels SET lang=?, lang_conf=? WHERE channel_id=?", out)
        db.commit()
        last_rowid = rows[-1][0]
        processed += len(rows)
        named += sum(1 for language, _, _ in out if language)
        if processed % (batch_size * 10) == 0:
            print(f"  {processed:,}/{total:,}", flush=True)
    print(f"assigned {named:,} / {processed:,}")


# ────────────────────────────────────────────────────── stage: videos ──

ISO = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", re.I)


def seconds(duration: str) -> int:
    """PT12M34S -> 754. Exact, unlike parsing a localized '12:34' string."""
    m = ISO.fullmatch((duration or "").strip())
    if not m:
        return 0
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def candidates(db: sqlite3.Connection, lang: Optional[str], min_subs: int) -> list[tuple]:
    """Keep a channel unless it is confidently a *different* language.

    Description is a strong precision signal and a weak recall one, so it is
    used only to exclude. Channels with no usable text stay in and are settled
    by defaultAudioLanguage below. A hidden subscriber count is unknown, not
    zero, so it cannot safely be rejected by the minimum threshold.
    """
    sql = """SELECT channel_id, uploads FROM channels
             WHERE uploads IS NOT NULL AND videos_at IS NULL
               AND (subscribers >= ? OR subscribers IS NULL)"""
    args: list[Any] = [min_subs]
    if lang:
        sql += " AND (lang = ? OR lang IS NULL)"
        args.append(lang)
    # Subscribers, not crawl_count: being linked across many monthly crawls
    # says a channel is old and blog-referenced, which is not the same as being
    # worth 2 units. A hidden count sorts last -- unknown, so unranked.
    return db.execute(sql + " ORDER BY subscribers IS NULL, subscribers DESC",
                      args).fetchall()


def audio_language(langs: Sequence[str]) -> Optional[str]:
    """Return a stable, sufficiently-supported majority audio language."""
    if len(langs) < MIN_AUDIO_LANG_SAMPLES:
        return None
    counts = Counter(langs)
    top_count = max(counts.values())
    winners = sorted(lang for lang, count in counts.items() if count == top_count)
    if len(winners) != 1 or top_count * 2 <= len(langs):
        return None
    return winners[0]


def videos(db: sqlite3.Connection, yt: YouTube, lang: Optional[str],
           min_subs: int, sample: int) -> None:
    todo = candidates(db, lang, min_subs)
    print(f"{len(todo):,} channels to fetch ({2 * len(todo):,} units)", flush=True)
    for n, (cid, uploads) in enumerate(todo, 1):
        try:
            ids = yt.playlist(uploads, sample)
            items = yt.videos(ids) if ids else []
        except Budget as why:
            # Distinguish "my --budget ran out" from "Google refused": the first
            # is a choice, the second means the day is over.
            print(f"stopped at {n:,}/{len(todo):,}: {why or 'local budget reached'}")
            break
        except Gone:
            # The uploads playlist is gone: terminated, or no public videos.
            # Permanent, so stamp it or it is re-bought on every run.
            db.execute("""UPDATE channels SET videos_at=datetime('now'),
                          note='no_uploads' WHERE channel_id=?""", (cid,))
            db.commit(); continue
        except RuntimeError as exc:
            # A transport/service failure is retryable. Do not stamp videos_at:
            # that is the durable marker the stage completed.
            db.execute("UPDATE channels SET note=? WHERE channel_id=?",
                       (f"videos_error:{str(exc)[:187]}", cid))
            db.commit(); continue
        if items:
            db.executemany(INSERT_VIDEO.format("REPLACE"), video_rows(items))
        langs = [v["snippet"].get("defaultAudioLanguage", "").split("-")[0].lower()
                 for v in items if v["snippet"].get("defaultAudioLanguage")]
        cats = [v["snippet"].get("categoryId") for v in items]
        db.execute("""UPDATE channels SET videos_at=datetime('now'), audio_lang=?,
                      music_share=?,
                      note=CASE WHEN note LIKE 'videos_error:%' THEN NULL ELSE note END
                      WHERE channel_id=?""",
                   (audio_language(langs),
                    cats.count(MUSIC_CATEGORY) / len(cats) if cats else None,
                    cid))
        db.commit()
        if n % 100 == 0:
            print(f"  {n:,}/{len(todo):,}  [{yt.used}/{yt.budget} units]", flush=True)


def video_rows(items: Sequence[dict], source: str = "uploads") -> list[tuple]:
    """Storable rows only. channel_id is NOT NULL, and the two INSERT verbs
    disagree about a violation -- OR REPLACE aborts the whole executemany with
    an IntegrityError that neither except clause catches, OR IGNORE drops the
    row without a word. An item with no snippet.channelId cannot be attributed
    to anything, so it is dropped once, here, and both stages behave alike."""
    return [video_row(i, source) for i in items
            if (i.get("snippet") or {}).get("channelId")]


def video_row(item: dict, source: str = "uploads") -> tuple:
    sn, st, cd = item["snippet"], item.get("statistics", {}), item.get("contentDetails", {})
    return (item["id"], sn.get("channelId"), (sn.get("title") or "").strip(),
            sn.get("description"), sn.get("publishedAt"),
            int(st.get("viewCount") or 0), int(st.get("likeCount") or 0),
            int(st.get("commentCount") or 0), seconds(cd.get("duration", "")),
            sn.get("categoryId"), sn.get("defaultAudioLanguage"),
            cd.get("caption"), sn.get("liveBroadcastContent"), source)


# ═══════════════════════════════════════════════════════════ selection ══
#
# Discovery fills the store; selection decides what is worth paying for next
# (classify: tokens, expand: 100 units) and finally what enters the ingestion
# queue. Every gate reads cached rows only.

@dataclass
class Gates:
    """Channel-level thresholds, measured on the Spanish pool.

    min_views_per_sub is the old 1%-of-subscribers rule (cuts ~16%).

    max_uploads_per_day is aimed at broadcast news and TV networks. They upload
    dozens of clips a day, so a 50-video sample of them spans hours rather than
    years -- every statistic below is then computed over one news cycle -- and
    the content is stale within a fortnight regardless. 2/day keeps daily
    vloggers and cuts the wire services.

    max_music is only a prior on where to spend; the real music filter is per
    video, in select(). max_sensitivity and min_intellectuality come from
    classify() and are the reason it runs before expand() spends 101 units."""
    min_subs: int = 10_000
    min_views_per_sub: float = 0.01
    max_uploads_per_day: float = 2.0
    max_music: float = 0.5
    max_sensitivity: float = 0.5
    min_intellectuality: float = 0.3
    min_sample: int = 5           # sampled uploads needed to judge a channel


# Stats come from the recency-ordered uploads sample only. search results are
# top-viewed by construction and would inflate every ratio they touched.
CHANNEL_STATS = """
    SELECT c.channel_id, c.title, c.subscribers, c.music_share,
           c.sensitivity, c.intellectuality, c.classified_at, c.expanded_at,
           COUNT(*) AS n, AVG(v.views) AS avg_views,
           COUNT(*) * 1.0 / MAX(1.0, julianday(MAX(v.published_at))
                                     - julianday(MIN(v.published_at))) AS per_day
    FROM channels c JOIN videos v USING (channel_id)
    WHERE COALESCE(c.audio_lang, c.lang) = ? AND c.videos_at IS NOT NULL
      AND (c.subscribers >= ? OR c.subscribers IS NULL)
      AND v.source = 'uploads' AND v.live = 'none'
    GROUP BY c.channel_id
"""


def reject(r: dict, g: Gates, need_llm: bool) -> Optional[str]:
    """Why a channel fails, or None. Pure, so thresholds are testable bare."""
    if r["n"] < g.min_sample:
        return "sample"
    if r["music_share"] is not None and r["music_share"] > g.max_music:
        return "music"
    # NULL subscribers means hidden -- unknown, so unrankable, and it passes.
    # 0 is a real count that 9,618 channels report, and it is not the same
    # thing: no view total clears a positive ratio against it, and dividing by
    # it raises. `if r["subscribers"]` conflated the two, so a zero-subscriber
    # channel skipped this gate exactly like a hidden one.
    subs = r["subscribers"]
    if subs is not None and g.min_views_per_sub > 0:
        if subs == 0 or (r["avg_views"] or 0) / subs < g.min_views_per_sub:
            return "engagement"
    # per_day is NULL when a published_at will not parse: unknown cadence, so
    # it cannot fail the gate (and None > float would abort the whole stage).
    if r["per_day"] is not None and r["per_day"] > g.max_uploads_per_day:
        return "upload_rate"
    if need_llm:
        if r["classified_at"] is None:
            return "unclassified"
        if r["sensitivity"] is not None and r["sensitivity"] > g.max_sensitivity:
            return "sensitivity"
        if (r["intellectuality"] is not None
                and r["intellectuality"] < g.min_intellectuality):
            return "intellectuality"
    return None


def qualified(db: sqlite3.Connection, lang: str, g: Gates,
              need_llm: bool) -> tuple[list[dict], Counter]:
    """Channels that clear the gates, and a funnel of why the rest did not.

    Reads through cursor.description rather than setting db.row_factory: the
    factory is connection-wide, and a stats query has no business changing how
    every other query in the process returns its rows."""
    cursor = db.execute(CHANNEL_STATS, (lang, g.min_subs))
    columns = [d[0] for d in cursor.description]
    passed, funnel = [], Counter()
    for row in cursor:
        r = dict(zip(columns, row))
        why = reject(r, g, need_llm)
        if why:
            funnel[why] += 1
        else:
            passed.append(r)
    print(f"  passed {len(passed):,}"
          + "".join(f"  {k} {v:,}" for k, v in sorted(funnel.items())), flush=True)
    return passed, funnel


# ───────────────────────────────────────────────────── stage: classify ──

# Music is deliberately not asked about: it is a per-video fact answered by
# category_id, and title guesses were worse. Language is settled upstream.
CLASSIFY_PROMPT = """Video titles from the YouTube channel "{name}", which publishes in {lang}.
Rate the channel as a whole on three 0-1 scales:
  sensitivity      how likely the content involves drugs, sexual content, graphic
                   violence, gambling or hate (1 = certainly)
  intellectuality  how much it explains, analyses or teaches, as opposed to
                   reacting, pranking or gossiping
Judge the channel, not single titles. Reply with JSON only.

Titles:
{titles}"""


def verdict_for(name: str, titles: Sequence[str], lang: str) -> dict[str, float]:
    """One MODEL_FAST call, imported lazily so harvest/enrich need no LLM key."""
    from pydantic import BaseModel
    from llm_client import parse_structured
    from models import MODEL_FAST

    class ChannelVerdict(BaseModel):
        sensitivity: float
        intellectuality: float

    prompt = CLASSIFY_PROMPT.format(name=name, lang=lang, titles="\n".join(titles))
    v = parse_structured(model=MODEL_FAST, messages=[{"role": "user", "content": prompt}],
                         schema_model=ChannelVerdict, reasoning={"enabled": False},
                         max_tokens=200, temperature=0.2)
    clamp = lambda x: min(1.0, max(0.0, float(x)))
    return {"sensitivity": clamp(v.sensitivity),
            "intellectuality": clamp(v.intellectuality)}


def classify(db: sqlite3.Connection, lang: str, g: Gates, limit: int,
             workers: int = CLASSIFY_WORKERS) -> None:
    """One LLM call per channel, `workers` of them in flight.

    The call is ~11s of waiting and no local work, so sequentially this is
    hours for a pool of this size. Only the requests are parallel: titles are
    read and verdicts are written on this thread, one commit per channel, so
    the stage stays resumable exactly as before and sqlite sees a single
    writer."""
    passed, funnel = qualified(db, lang, g, need_llm=False)
    todo = [r for r in passed if r["classified_at"] is None][:limit]
    print(f"classifying {len(todo):,} channels, {workers} at a time", flush=True)
    work = [(r, [t for (t,) in db.execute(
                "SELECT title FROM videos WHERE channel_id=? ORDER BY views DESC LIMIT 50",
                (r["channel_id"],))]) for r in todo]
    done = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(verdict_for, r["title"] or r["channel_id"], titles, lang): r
                   for r, titles in work}
        for future in as_completed(futures):
            r = futures[future]
            try:
                v = future.result()
            except Exception as exc:             # noqa: BLE001 - one channel, not the run
                failed += 1
                print(f"  {r['channel_id']}: {type(exc).__name__}: {str(exc)[:100]}", flush=True)
                continue
            db.execute("""UPDATE channels SET classified_at=datetime('now'),
                          sensitivity=?, intellectuality=? WHERE channel_id=?""",
                       (v["sensitivity"], v["intellectuality"], r["channel_id"]))
            db.commit()
            done += 1
            if done % 50 == 0:
                print(f"  {done:,}/{len(todo):,}", flush=True)
    print(f"classified {done:,}, failed {failed:,}")


# ─────────────────────────────────────────────────────── stage: expand ──

def expand(db: sqlite3.Connection, yt: YouTube, lang: str, g: Gates) -> None:
    """Top-viewed videos for every channel that cleared all gates, LLM included.
    Merged with INSERT OR IGNORE so a video already in the uploads sample keeps
    source='uploads' and stays part of the channel statistics."""
    passed, funnel = qualified(db, lang, g, need_llm=True)
    todo = [r for r in passed if r["expanded_at"] is None]
    # Reach first: 101 units buys the most where the typical video travels.
    todo.sort(key=lambda r: -(r["avg_views"] or 0))
    print(f"{len(todo):,} channels to expand ({101 * len(todo):,} units)", flush=True)
    for n, r in enumerate(todo, 1):
        cid = r["channel_id"]
        try:
            ids = yt.search(cid)
            items = yt.videos(ids) if ids else []
        except Budget as why:
            print(f"stopped at {n:,}/{len(todo):,}: {why or 'local budget reached'}")
            break
        except Gone:
            # Stamped, not retried: without this a permanently missing channel
            # costs 100 units on every single run, forever.
            db.execute("""UPDATE channels SET expanded_at=datetime('now'),
                          note='no_search' WHERE channel_id=?""", (cid,))
            db.commit(); continue
        except RuntimeError as exc:
            print(f"  {cid}: {str(exc)[:100]}", flush=True)
            continue                             # no stamp: retried next run
        if items:
            db.executemany(INSERT_VIDEO.format("IGNORE"), video_rows(items, "search"))
        db.execute("UPDATE channels SET expanded_at=datetime('now') WHERE channel_id=?", (cid,))
        db.commit()
        if n % 20 == 0:
            print(f"  {n:,}/{len(todo):,}  [{yt.used}/{yt.budget} units]", flush=True)


# ─────────────────────────────────────────────────────── stage: select ──

def score(minutes: int, views: int, lo: float, hi: float) -> float:
    short = 1 - min(1.0, max(0.0, (minutes - 8) / 17))     # 8-25 min preferred
    seen = 0.0 if hi <= lo else min(1.0, max(0.0, (views - lo) / (hi - lo)))
    return (1 - VIEW_BIAS) * short + VIEW_BIAS * seen


def select(db: sqlite3.Connection, lang: str, g: Gates, top_n: int = TOP_N) -> list[dict]:
    """The deliverable: ranked queue rows. Channels pass the gates; videos are
    then filtered individually -- music by category_id, not by channel, so an
    artist's interview survives and their music videos do not -- and ranked
    within their channel over uploads and search results together."""
    passed, funnel = qualified(db, lang, g, need_llm=True)
    keep = {r["channel_id"] for r in passed}
    rows = db.execute("""SELECT v.channel_id, v.video_id, v.title, COALESCE(v.views, 0),
                                v.duration_s
                         FROM videos v JOIN channels c USING (channel_id)
                         WHERE COALESCE(c.audio_lang, c.lang) = ? AND v.live = 'none'
                           AND COALESCE(v.category_id, '') != ?
                           AND v.duration_s BETWEEN 60 AND ?""",
                      (lang, MUSIC_CATEGORY, MAX_MINUTES * 60)).fetchall()
    by_channel: dict[str, list[dict]] = {}
    for cid, vid, title, views, dur in rows:
        if cid in keep:
            by_channel.setdefault(cid, []).append(
                {"video_id": vid, "channel_id": cid, "lang": lang, "title": title,
                 "duration_s": dur, "views": views})
    out = []
    for vids in by_channel.values():
        lo, hi = min(v["views"] for v in vids), max(v["views"] for v in vids)
        for v in vids:
            v["score"] = round(score(v["duration_s"] // 60, v["views"], lo, hi), 4)
        vids.sort(key=lambda v: -v["score"])
        out.extend(vids[:top_n])
    print(f"{len(by_channel):,} channels, {len(out):,} videos selected")
    return out


def push(rows: list[dict], sb=None) -> int:
    """Into video_queue. ignore_duplicates: a row that exists keeps its status,
    which is the property the JSON worklist never had."""
    from languages import require_code
    if sb is None:
        from supabase_client import supabase as sb   # verifies service_role
    for r in rows:
        require_code(r["lang"])
    written = 0
    for chunk in batched(rows, 500):
        res = sb.table("video_queue").upsert(chunk, on_conflict="video_id",
                                             ignore_duplicates=True).execute()
        written += len(res.data or [])
    return written


def report(db: sqlite3.Connection) -> None:
    q = lambda s, *a: db.execute(s, a).fetchone()[0]
    print(f"channels        {q('SELECT COUNT(*) FROM channels'):>9,}")
    print(f"  enriched      {q('SELECT COUNT(*) FROM channels WHERE enriched_at IS NOT NULL'):>9,}")
    print(f"  detected      {q('SELECT COUNT(*) FROM channels WHERE lang IS NOT NULL'):>9,}")
    print(f"  videos cached {q('SELECT COUNT(*) FROM channels WHERE videos_at IS NOT NULL'):>9,}")
    print(f"  classified    {q('SELECT COUNT(*) FROM channels WHERE classified_at IS NOT NULL'):>9,}")
    print(f"  expanded      {q('SELECT COUNT(*) FROM channels WHERE expanded_at IS NOT NULL'):>9,}")
    print(f"videos          {q('SELECT COUNT(*) FROM videos'):>9,}")
    cap = db.execute("SELECT COALESCE(SUM(caption='true'), 0), COUNT(*) FROM videos").fetchone()
    if cap[1]:
        print(f"  with captions {cap[0]:>9,}  ({100 * cap[0] / cap[1]:.0f}%)")
    print("\nby language (channels with >=10k subs):")
    for lang, n in db.execute("""SELECT COALESCE(audio_lang, lang) l, COUNT(*)
                                 FROM channels WHERE subscribers >= 10000 AND l IS NOT NULL
                                 GROUP BY l ORDER BY 2 DESC LIMIT 8"""):
        print(f"   {lang:5} {n:>7,}")


# ───────────────────────────────────────────────────────────────── cli ──

def sample_size(value: str) -> int:
    """Keep the two-API-units-per-channel contract explicit."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--sample must be an integer from 1 to 50") from exc
    if not 1 <= n <= 50:
        raise argparse.ArgumentTypeError("--sample must be from 1 to 50 (one API page)")
    return n


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices="harvest enrich detect videos classify expand select report".split())
    p.add_argument("--db", type=Path, default=DB)
    p.add_argument("--budget", type=int, default=9000, help="quota units")
    p.add_argument("--lang", help="ISO 639-1, e.g. es")
    p.add_argument("--sample", type=sample_size, default=50,
                   help="videos: uploads sampled per channel (1-50; one API page)")
    p.add_argument("--stale-days", type=int, default=30, help="re-enrich after N days")
    p.add_argument("--crawls", nargs="*", default=CRAWLS)
    gates = p.add_argument_group("selection gates")
    gates.add_argument("--min-subs", type=int, default=10_000,
                       help="skip below this subscriber count; hidden counts always pass")
    gates.add_argument("--min-views-per-sub", type=float, default=0.01,
                       help="average views must reach this fraction of subscribers")
    gates.add_argument("--max-uploads-per-day", type=float, default=2.0,
                       help="skip faster uploaders; aimed at broadcast news")
    gates.add_argument("--max-music", type=float, default=0.5,
                       help="skip channels this fraction of whose sampled videos are music")
    gates.add_argument("--max-sensitivity", type=float, default=0.5,
                       help="skip channels the classifier rates riskier than this")
    gates.add_argument("--min-intellectuality", type=float, default=0.3,
                       help="skip channels the classifier rates less explanatory than this")
    gates.add_argument("--min-sample", type=int, default=5,
                       help="sampled uploads needed before a channel can be judged")
    p.add_argument("--limit", type=int, default=10_000, help="classify: channels per run")
    p.add_argument("--top", type=int, default=TOP_N, help="select: videos per channel")
    p.add_argument("--push", action="store_true", help="select: upsert into video_queue")
    p.add_argument("--out", type=Path, help="select: also write the rows as JSON")
    a = p.parse_args()
    g = Gates(a.min_subs, a.min_views_per_sub, a.max_uploads_per_day, a.max_music,
              a.max_sensitivity, a.min_intellectuality, a.min_sample)

    db = connect(a.db)
    if a.stage == "report":
        return report(db)
    if a.stage in ("classify", "expand", "select") and not a.lang:
        sys.exit(f"{a.stage} needs --lang")
    if a.stage == "select":
        rows = select(db, a.lang, g, a.top)
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), "utf-8")
            print(f"wrote {a.out}")
        if a.push:
            print(f"queued {push(rows):,} new rows")
        elif not a.out:
            print("dry run: pass --push to queue, --out to inspect")
        return

    lock(a.db)
    if a.stage == "harvest":
        harvest(db, a.crawls)
    elif a.stage == "detect":
        detect(db)
    elif a.stage == "classify":
        classify(db, a.lang, g, a.limit)
    else:
        yt = YouTube(a.budget)
        if a.stage == "enrich":
            enrich(db, yt, a.stale_days)
        elif a.stage == "videos":
            videos(db, yt, a.lang, g.min_subs, a.sample)
        else:
            expand(db, yt, a.lang, g)
        print(f"spent {yt.used:,} quota units")
    report(db)


if __name__ == "__main__":
    main()
