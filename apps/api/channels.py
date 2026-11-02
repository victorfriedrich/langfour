"""
Favourite channels and a channel's Langfour tab on YouTube
(docs/plans/youtube-plan.md, features 4 and 8).

  - favourite: a plain toggle per learner and channel (sql/channel_favourites.sql).
    A new favourite queues the channel for indexing. Its pending discovery
    rows in video_queue move up to FAVOURITE_PRIORITY, and with YOUTUBE_API_KEY
    set its uploads not queued yet go in at that tier too. That lifts
    discovery's cap of 15 videos per channel (ytpipeline select) for this
    channel. The moved rows become source 'user', so the next `ytpipeline
    select --push`, which replaces pending discovery rows, keeps them.
    Unfavouriting leaves the queue alone. Uploads are only listed for a
    language the API's own worker drains, for a channel in that language, and
    within per-user limits: each listing spends YouTube quota and each row a
    proxy download, and the extension's relay lets the page itself call these
    endpoints. A listing that didn't finish is tried again on the next visit to
    the channel; uploads_outcome says how the last one went, which is how the
    tab can say why nothing is being added.
  - progress: "34 of 212 videos added" while a favourite channel still has
    videos to come and the worker is draining its language. Added counts done
    rows; the total adds every row still waiting. Once nothing has finished
    for STALL_AFTER, the total is dropped, so a channel whose videos keep
    failing doesn't show a number that never moves.
  - at your level: the channel's indexed videos where the learner knows
    AT_LEVEL of the words spoken.
  - core words: words the learner doesn't have yet that appear in at least
    half of the channel's videos, most spoken first, up to CORE_WORDS, with
    how much of the channel's speech they'd understand before and after. Only
    when that gain is CORE_MIN_GAIN or more: for most channels 25 words add
    about 2 points, which isn't worth a card. One batch per learner and
    channel: added words stay "not known" while they're learned, so without
    this the card would come back with the next 25 at the same "before".

Coverage counts every word spoken, as the recommender's percentages do. The
channel's videos are the done rows of video_queue that the recommender loaded
at boot, so a video ingested since then counts as added before it counts here.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import numpy as np
import requests
from pydantic import BaseModel

import ingest
import ingest_worker
import video_quality
from paths import processed_file
from recommender import MIN_DISTINCT_WORDS
from videoparsing import transcript_language_matches
from vocabulary import Language, VocabularyStore
from ytpipeline import audio_language, seconds

log = logging.getLogger(__name__)

CHANNEL_ID = r"^UC[A-Za-z0-9_-]{22}$"

AT_LEVEL = 0.95        # share of words heard known: the comprehension threshold
CORE_WORDS = 25
CORE_SHARE = 0.5       # of the channel's videos a core word appears in
CORE_MIN_VIDEOS = 5    # fewer, and "half the channel's videos" means two
CORE_MIN_GAIN = 0.03
CORE_CANDIDATES = 200  # looked up to find CORE_WORDS valid ones
STALL_AFTER = timedelta(days=1)
CONTEXT_WORDS = 10     # words either side of a core word in its context line
CONTEXT_FILES = 10     # transcripts read to find context lines

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
MAX_UPLOADS = 500      # newest first; 20 quota units at most
# Shorts and clips below, marathons above: neither is worth a proxy download
# for a learner.
MIN_SECONDS, MAX_SECONDS = 3 * 60, 60 * 60
# Above discovery, below the user tier (10): a favourite is up to 500 videos,
# and someone who asked for one video with "+ Add" shouldn't wait behind them.
FAVOURITE_PRIORITY = 5
LISTINGS_PER_DAY = 20  # per user: 400 quota units at most, of 10,000 a day
MAX_WAITING = 1000     # a user's rows waiting in the queue before no more go in

_PAGE = 1000  # PostgREST's row cap per request
_IN_CHUNK = 200


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class Progress(BaseModel):
    added: int
    total: int | None  # None once the channel stalls


class CoreWord(BaseModel):
    word_id: int
    word: str


class CoreWords(BaseModel):
    words: list[CoreWord]  # most spoken first
    before: float          # % of the channel's speech understood now
    after: float           # ... with these words known


class ChannelView(BaseModel):
    favourite: bool
    # A favourite's upload listing: not finished yet (and tried again on the
    # next visit), done, or skipped as the channel is in another language.
    uploads: Literal["pending", "queued", "other_language"] | None
    added: int             # done rows, including any the recommender hasn't loaded
    videos: int            # indexed videos the numbers below come from
    at_level: int
    progress: Progress | None
    core_words: CoreWords | None


class FavouriteRequest(BaseModel):
    language: Language
    favourite: bool


class Favourite(BaseModel):
    favourite: bool


class CoreWordsRequest(BaseModel):
    language: Language


class CoreWordsAdded(BaseModel):
    added: list[str]


# ---------------------------------------------------------------------------
# Storage. Like vocabulary.VocabularyStore: everything that touches Supabase
# is here, so the logic below runs against an in-memory stand-in in tests.
# ---------------------------------------------------------------------------

class ChannelStore:
    def __init__(self, client):
        self.db = client

    def favourite_row(self, user_id: str, channel_id: str) -> dict | None:
        """{created_at, lang, uploads_outcome}, or None if not a favourite."""
        rows = (self.db.table("channel_favourites").select("created_at,lang,uploads_outcome")
                .eq("user_id", user_id).eq("channel_id", channel_id).limit(1).execute().data)
        return rows[0] if rows else None

    def set_uploads_outcome(self, user_id: str, channel_id: str, outcome: str) -> None:
        (self.db.table("channel_favourites").update({"uploads_outcome": outcome})
         .eq("user_id", user_id).eq("channel_id", channel_id).execute())

    def favourite(self, user_id: str, channel_id: str, language: str) -> bool:
        """True when the channel wasn't a favourite already."""
        res = (self.db.table("channel_favourites")
               .upsert({"user_id": user_id, "channel_id": channel_id, "lang": language},
                       on_conflict="user_id,channel_id", ignore_duplicates=True)
               .execute())
        return bool(res.data)

    def unfavourite(self, user_id: str, channel_id: str) -> None:
        (self.db.table("channel_favourites").delete()
         .eq("user_id", user_id).eq("channel_id", channel_id).execute())

    def queue_rows(self, channel_id: str, language: str) -> list[dict]:
        """The channel's video_queue rows: [{video_id, status, attempts, done_at}]."""
        out: list[dict] = []
        while True:
            rows = (self.db.table(ingest.TABLE).select("video_id,status,attempts,done_at")
                    .eq("channel_id", channel_id).eq("lang", language).order("video_id")
                    .range(len(out), len(out) + _PAGE - 1).execute().data or [])
            out += rows
            if len(rows) < _PAGE:
                return out

    def promote(self, user_id: str, channel_id: str, language: str) -> int:
        """Pending discovery rows of the channel up to FAVOURITE_PRIORITY."""
        rows = (self.db.table(ingest.TABLE)
                .update({"priority": FAVOURITE_PRIORITY, "source": "user",
                         "submitted_by": user_id})
                .eq("channel_id", channel_id).eq("lang", language)
                .eq("status", "pending").eq("source", "discovery")
                .execute().data)
        return len(rows or [])

    def enqueue(self, rows: list[dict]) -> int:
        """New rows only: a video already queued keeps its row and status."""
        written = 0
        for chunk in ingest.batched(rows, 500):
            res = (self.db.table(ingest.TABLE)
                   .upsert(chunk, on_conflict="video_id", ignore_duplicates=True).execute())
            written += len(res.data or [])
        return written

    def waiting_rows(self, user_id: str) -> int:
        """Rows this user put in the queue that are still waiting."""
        res = (self.db.table(ingest.TABLE).select("video_id", count="exact")
               .eq("submitted_by", user_id).eq("status", "pending").limit(1).execute())
        return res.count or 0

    def _word_ids(self, table: str, user_id: str) -> set[int]:
        out: set[int] = set()
        start = 0
        while True:
            rows = (self.db.table(table).select("word_id").eq("user_id", user_id)
                    .order("word_id").range(start, start + _PAGE - 1).execute().data or [])
            out |= {r["word_id"] for r in rows}
            if len(rows) < _PAGE:
                return out
            start += _PAGE

    def known_words(self, user_id: str) -> set[int]:
        """As Recommender.get_known_words: declared known or learned in reviews."""
        return self._word_ids("user_known_words", user_id)

    def listed_words(self, user_id: str) -> set[int]:
        """Every word in the user's list, whatever its status."""
        return self._word_ids("userwords", user_id)

    def added_from_channel(self, user_id: str, channel_id: str) -> list[str]:
        """The words already added from this channel's card."""
        res = (self.db.table("userwords").select("words!inner(root)")
               .eq("user_id", user_id).eq("source", channel_id).execute())
        return [r["words"]["root"] for r in res.data or []]

    def broken(self, video_ids: list[str]) -> set[str]:
        """The videos the quality scores reject for their transcript: garbled
        captions, a lesson for another language, a song. Not low_quality,
        which is a judgement of taste the learner overruled by choosing the
        channel."""
        out: set[str] = set()
        for chunk in ingest.batched(video_ids, _IN_CHUNK):
            res = (self.db.table("video_scores")
                   .select("video_id,p_garbled,p_foreign_lesson,p_sung,content,transferable")
                   .in_("video_id", chunk).execute())
            out |= {r["video_id"] for r in res.data or []
                    if video_quality.hidden(r) not in (None, "low_quality")}
        return out

    def valid_words(self, word_ids: list[int]) -> dict[int, str]:
        """word_id -> root for the ones the dictionary review kept."""
        out: dict[int, str] = {}
        for chunk in ingest.batched(word_ids, _IN_CHUNK):
            res = (self.db.table("words").select("id, root").in_("id", chunk)
                   .eq("status", "valid").execute())
            out |= {r["id"]: r["root"] for r in res.data or []}
        return out


def get_channel_store() -> ChannelStore:
    from supabase_client import supabase
    return ChannelStore(supabase)


# ---------------------------------------------------------------------------
# The channel in the recommender's matrix
# ---------------------------------------------------------------------------

_rows_by_video: dict[str, tuple[list[str], dict[str, int]]] = {}


def _row_index(recommender, language: str) -> dict[str, int]:
    """video id -> matrix row, rebuilt if the recommender reloads the language."""
    files = recommender.filenames[language]
    cached = _rows_by_video.get(language)
    if cached is None or cached[0] is not files:
        cached = (files, {f.replace("_processed.json", ""): i for i, f in enumerate(files)})
        _rows_by_video[language] = cached
    return cached[1]


def channel_videos(store: ChannelStore, recommender, channel_id: str,
                   language: str) -> tuple[list[dict], list[tuple[str, int]]]:
    """The channel's queue rows, and (video id, matrix row) for its videos the
    numbers come from: done, loaded at boot, not broken (ChannelStore.broken),
    not a clip."""
    recommender._ensure_language_loaded(language)
    queue = store.queue_rows(channel_id, language)
    index = _row_index(recommender, language)
    distinct = recommender.distinct_words_per_doc[language]
    loaded = [(r["video_id"], index[r["video_id"]]) for r in queue
              if r["status"] == "done" and r["video_id"] in index]
    broken = store.broken([v for v, _ in loaded]) if loaded else set()
    return queue, [(v, row) for v, row in loaded
                   if v not in broken and distinct[row] >= MIN_DISTINCT_WORDS]


def _known_vector(width: int, word_ids: Iterable[int]) -> np.ndarray:
    vector = np.zeros(width, dtype=bool)
    ids = [w for w in word_ids if 0 <= w < width]
    vector[ids] = True
    return vector


def at_level(recommender, language: str, rows: list[int], known: set[int]) -> int:
    if not rows:
        return 0
    counts = recommender.matrices[language][rows]
    known_vector = _known_vector(counts.shape[1], known).astype(np.int32)
    spoken = np.asarray(counts.sum(axis=1)).ravel()
    heard = counts.dot(known_vector)
    return int(np.count_nonzero((spoken > 0) & (heard >= AT_LEVEL * spoken)))


def core_words(store: ChannelStore, recommender, language: str, rows: list[int],
               known: set[int], listed: set[int]) -> CoreWords | None:
    if len(rows) < CORE_MIN_VIDEOS:
        return None
    counts = recommender.matrices[language][rows]
    spoken = np.asarray(counts.sum(axis=0)).ravel()
    videos = np.asarray(recommender.presence[language][rows].sum(axis=0)).ravel()
    total = spoken.sum()
    if not total:
        return None
    known_vector = _known_vector(counts.shape[1], known)
    before = spoken[known_vector].sum() / total

    eligible = (videos >= CORE_SHARE * len(rows)) & ~known_vector
    eligible &= ~_known_vector(counts.shape[1], listed)
    candidates = np.flatnonzero(eligible)
    # Most spoken first; ties to the lower id, the more common word.
    candidates = candidates[np.lexsort((candidates, -spoken[candidates]))][:CORE_CANDIDATES]
    valid = store.valid_words([int(w) for w in candidates])
    chosen = [int(w) for w in candidates if int(w) in valid][:CORE_WORDS]
    if not chosen:
        return None
    after = before + spoken[chosen].sum() / total
    if after - before < CORE_MIN_GAIN:
        return None
    return CoreWords(words=[CoreWord(word_id=w, word=valid[w]) for w in chosen],
                     before=round(float(before) * 100, 1), after=round(float(after) * 100, 1))


def progress(rows: list[dict], favourited_at: datetime | None, now: datetime) -> Progress | None:
    if favourited_at is None:
        return None
    done = [r for r in rows if r["status"] == "done"]
    waiting = [r for r in rows if r["status"] == "processing"
               or (r["status"] == "pending" and (r.get("attempts") or 0) < ingest.MAX_ATTEMPTS)]
    if not waiting:
        return None
    last = max([favourited_at] + [datetime.fromisoformat(r["done_at"])
                                  for r in done if r.get("done_at")])
    stalled = now - last > STALL_AFTER
    return Progress(added=len(done), total=None if stalled else len(done) + len(waiting))


def channel_view(store: ChannelStore, recommender, user_id: str, channel_id: str,
                 language: str, now: datetime | None = None) -> ChannelView:
    favourite = store.favourite_row(user_id, channel_id)
    favourited_at = datetime.fromisoformat(favourite["created_at"]) if favourite else None
    queue, videos = channel_videos(store, recommender, channel_id, language)
    rows = [row for _, row in videos]
    known = store.known_words(user_id) if rows else set()
    # Every query the card needs, only for a channel that can have one.
    card = len(rows) >= CORE_MIN_VIDEOS and not store.added_from_channel(user_id, channel_id)
    listed = store.listed_words(user_id) if card else set()
    return ChannelView(
        favourite=favourite is not None,
        uploads=(favourite.get("uploads_outcome") or "pending") if favourite else None,
        added=sum(r["status"] == "done" for r in queue),
        videos=len(rows),
        at_level=at_level(recommender, language, rows, known),
        progress=(progress(queue, favourited_at, now or datetime.now(UTC))
                  if worker_language() == language else None),
        core_words=core_words(store, recommender, language, rows, known, listed) if card else None,
    )


# ---------------------------------------------------------------------------
# Favourite
# ---------------------------------------------------------------------------

def worker_language() -> str | None:
    """The language the API's own ingest worker drains, if it runs."""
    configured = ingest_worker.configured()
    return configured[0] if configured else None


def set_favourite(store: ChannelStore, user_id: str, channel_id: str, language: str,
                  favourite: bool) -> bool:
    """True when its uploads should be listed: a new favourite, or one whose
    listing hasn't finished."""
    if not favourite:
        store.unfavourite(user_id, channel_id)
        return False
    if not store.favourite(user_id, channel_id, language):
        return needs_listing(store.favourite_row(user_id, channel_id))
    promoted = store.promote(user_id, channel_id, language)
    log.info("favourite %s: %d pending rows moved up", channel_id, promoted)
    return True


def needs_listing(favourite: dict | None) -> bool:
    return favourite is not None and favourite.get("uploads_outcome") is None


def fetch_uploads(channel_id: str, key: str,
                  get: Callable[..., Any] = requests.get) -> list[dict]:
    """The channel's newest MAX_UPLOADS uploads that fit a learner: neither
    Shorts nor live now. 1 quota unit per 50 listed, 1 per 50 looked up.

    The key goes in a header: in the query string it would be in every
    HTTPError and ConnectionError message, and from there in the logs."""
    headers = {"X-Goog-Api-Key": key}
    ids: list[str] = []
    token = None
    while len(ids) < MAX_UPLOADS:
        params = {"part": "contentDetails", "playlistId": "UU" + channel_id[2:], "maxResults": 50}
        if token:
            params["pageToken"] = token
        res = get(f"{YOUTUBE_API}/playlistItems", params=params, headers=headers, timeout=15)
        if res.status_code == 404:  # no public uploads
            return []
        res.raise_for_status()
        body = res.json()
        ids += [i["contentDetails"]["videoId"] for i in body.get("items", [])]
        token = body.get("nextPageToken")
        if not token:
            break

    videos = []
    for chunk in ingest.batched(ids[:MAX_UPLOADS], 50):
        res = get(f"{YOUTUBE_API}/videos", headers=headers, timeout=15, params={
            "part": "snippet,contentDetails,statistics", "id": ",".join(chunk)})
        res.raise_for_status()
        for item in res.json().get("items", []):
            snippet = item["snippet"]
            length = seconds(item.get("contentDetails", {}).get("duration", ""))
            # liveBroadcastContent, as discovery does: a premiere is an
            # ordinary edited video, and also has liveStreamingDetails.
            if (snippet.get("liveBroadcastContent", "none") != "none"
                    or not MIN_SECONDS <= length <= MAX_SECONDS):
                continue
            videos.append({"video_id": item["id"],
                           "title": (snippet.get("title") or "").strip(),
                           "duration_s": length,
                           "views": int(item.get("statistics", {}).get("viewCount") or 0),
                           "audio": (snippet.get("defaultAudioLanguage") or "").split("-")[0].lower()})
    return videos


def in_language(uploads: list[dict], language: str, vetted: bool) -> list[dict]:
    """The uploads worth a proxy download for this language, without their
    "audio" field. A learner can favourite a channel in any language, and a
    transcript's language is otherwise only checked after that download.

    `vetted`: the channel already has transcripts in this language. If not,
    the channel must show it: its uploads' stated audio language, or failing
    that their titles. Short or unclear titles abstain, as the check on
    transcripts does."""
    stated = [v["audio"] for v in uploads if v["audio"]]
    if not vetted:
        majority = audio_language(stated)
        if majority is not None:
            if majority != language:
                return []
        elif not transcript_language_matches(" ".join(v["title"] for v in uploads), language):
            return []
    return [{k: v for k, v in upload.items() if k != "audio"}
            for upload in uploads if upload["audio"] in ("", language)]


def queue_uploads(store: ChannelStore, user_id: str, channel_id: str, language: str,
                  uploads: list[dict]) -> int:
    """Uploads the queue doesn't have yet, at FAVOURITE_PRIORITY. Within the
    channel the most viewed go first, as discovery's score leans on views."""
    if not uploads:
        return 0
    top = max(v["views"] for v in uploads) or 1
    rows = [{**v, "channel_id": channel_id, "lang": language, "source": "user",
             "priority": FAVOURITE_PRIORITY, "submitted_by": user_id,
             "score": round(v["views"] / top, 4)}
            for v in uploads]
    return store.enqueue(rows)


_listings: dict[str, list[float]] = defaultdict(list)
_listing_now: set[tuple[str, str]] = set()
_listings_lock = threading.Lock()


def _may_list(user_id: str, now: float | None = None) -> bool:
    """LISTINGS_PER_DAY per user, counted in memory: favouriting and
    unfavouriting in a loop leaves no row to count. A restart only forgets."""
    now = time.monotonic() if now is None else now
    with _listings_lock:
        recent = [t for t in _listings[user_id] if now - t < 86400]
        allowed = len(recent) < LISTINGS_PER_DAY
        _listings[user_id] = [*recent, now] if allowed else recent
    return allowed


def queue_channel(store: ChannelStore, user_id: str, channel_id: str, language: str,
                  key: str | None) -> int:
    """After a new favourite or a visit to one whose listing hasn't finished, in
    the background: the uploads list takes a few seconds for a big channel, and
    the button shouldn't wait on it. Every early way out leaves uploads_outcome
    null, so the next visit tries again."""
    if not key:
        log.info("favourite %s: YOUTUBE_API_KEY unset; only queued rows promoted", channel_id)
        return 0
    if worker_language() != language:
        log.info("favourite %s: no worker drains %s; uploads not listed", channel_id, language)
        return 0
    task = (user_id, channel_id)
    with _listings_lock:
        if task in _listing_now:
            return 0
        _listing_now.add(task)
    try:
        if store.waiting_rows(user_id) >= MAX_WAITING or not _may_list(user_id):
            log.info("favourite %s: user over the limits; uploads not listed", channel_id)
            return 0
        vetted = any(r["status"] == "done" for r in store.queue_rows(channel_id, language))
        uploads = fetch_uploads(channel_id, key)
        kept = in_language(uploads, language, vetted)
        added = queue_uploads(store, user_id, channel_id, language, kept)
        store.set_uploads_outcome(user_id, channel_id,
                                  "other_language" if uploads and not kept else "queued")
    except Exception:
        log.warning("favourite %s: could not queue its uploads", channel_id, exc_info=True)
        return 0
    finally:
        with _listings_lock:
            _listing_now.discard(task)
    log.info("favourite %s: %d uploads queued", channel_id, added)
    return added


# ---------------------------------------------------------------------------
# Core words to reviews
# ---------------------------------------------------------------------------

def context_lines(language: str, word_ids: list[int], videos: list[tuple[str, int]],
                  presence) -> dict[int, dict]:
    """word_id -> {media, title, sentence}: a line from one of the channel's
    videos where the word is said, for the saved event. Reads at most
    CONTEXT_FILES transcripts, the ones holding the most of the words."""
    wanted = set(word_ids)
    present = presence[[row for _, row in videos]][:, word_ids].toarray()
    holds = {video_id: {w for w, there in zip(word_ids, present[n], strict=True) if there}
             for n, (video_id, _) in enumerate(videos)}
    out: dict[int, dict] = {}
    for video_id, _ in sorted(videos, key=lambda v: -len(holds[v[0]]))[:CONTEXT_FILES]:
        missing = holds[video_id] - out.keys()
        if not missing:
            continue
        try:
            doc = json.loads(processed_file(language, video_id).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        tokens = doc.get("content") or []
        positions = [i for i, t in enumerate(tokens) if isinstance(t, dict) and t.get("id")]
        for n, i in enumerate(positions):
            word_id = tokens[i]["id"]
            if word_id not in missing or word_id in out:
                continue
            start = positions[max(0, n - CONTEXT_WORDS)]
            end = positions[min(len(positions) - 1, n + CONTEXT_WORDS)]
            line = "".join(str(t.get("content", "")) for t in tokens[start:end + 1]
                           if isinstance(t, dict))
            out[word_id] = {"media": f"youtube:{video_id}", "title": doc.get("title"),
                            "sentence": " ".join(line.split())}
        if len(out) == len(wanted):
            break
    return out


def add_core_words(store: ChannelStore, vocab: VocabularyStore, recommender, user_id: str,
                   channel_id: str, language: str) -> CoreWordsAdded:
    """The channel's core words, worked out again here rather than taken from
    the client, into the user's list as learning, each with a saved event
    carrying a line from the channel.

    Safe to retry. The events go first, so a failure there has added nothing,
    and a word with a saved event from this channel doesn't get a second; once
    words are in the list, this answers with them and adds no more."""
    already = store.added_from_channel(user_id, channel_id)
    if already:
        return CoreWordsAdded(added=already)
    _, videos = channel_videos(store, recommender, channel_id, language)
    rows = [row for _, row in videos]
    words = core_words(store, recommender, language, rows,
                       store.known_words(user_id), store.listed_words(user_id))
    if words is None:
        return CoreWordsAdded(added=[])
    ids = [w.word_id for w in words.words]
    contexts = context_lines(language, ids, videos, recommender.presence[language])
    saved = {e["word_id"] for e in vocab.events(user_id, ids, ["saved"])
             if (e.get("context") or {}).get("channel_id") == channel_id}
    vocab.insert_events([
        {"user_id": user_id, "word_id": w, "kind": "saved", "source": "video",
         "context": {"site": "youtube", "channel_id": channel_id, **contexts.get(w, {})}}
        for w in ids if w not in saved
    ])
    vocab.add_words(user_id, ids, "learning", source=channel_id)
    return CoreWordsAdded(added=[w.word for w in words.words])
