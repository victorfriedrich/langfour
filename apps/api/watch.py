"""
Which YouTube videos the user watched, and the next day's recap of their
words (docs/plans/youtube-plan.md, feature 2).

Two sources fill watch_events (sql/watch_events.sql), one row per video:

  - desktop: the extension counts the seconds played on youtube.com and
    reports a video once 70% of it was played.
  - history: with the user's consent, the extension reads
    youtube.com/feed/history, which also lists what they watched in the
    YouTube app on their phone, with each video's red progress bar.

The recommender leaves watched videos out (get_watched_videos), and the web
Videos page lists them with Unmark.

Only videos in Langfour's index for the user's language are kept: the
history page lists everything the account watched, and an id that isn't a
transcript here is dropped on arrival and never stored.

The recap ("Yesterday on YouTube") lists the new words that came up in at
least two of yesterday's videos, or three times or more, up to 8. "Add N to
reviews" adds them as learning, each with a sentence from the video it came
from. Learning words that came up need no decision: they are logged as
exposure (vocabulary.record_seen) once per word per video when the watch
lands.

The API runs this with the service role on behalf of the signed-in user, so
every query names the user explicitly.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

import paths
import vocabulary
from supabase_client import supabase
from vocabulary import Language, SeenRequest, VocabularyStore

# Played this much, a video counts as watched; the extension uses the same.
WATCHED_SHARE = 0.7
# History bars are rough: re-marking an unmarked video needs it to have grown.
REWATCH_GROWTH = 0.05
HISTORY_ITEMS = 500   # video ids per history read; the page shows ~100-200
WATCHED_LIST = 100
RECAP_WORDS = 8
RECAP_MIN_VIDEOS = 2  # a word qualifies by coming up in this many videos
RECAP_MIN_TIMES = 3   # or this many times in all
RECAP_WINDOW = timedelta(hours=26)  # a day, with room for a DST change
# A sentence for a saved word: long enough to say something, short enough
# for a card.
SENTENCE_WORDS = (4, 25)
MAX_SENTENCE_CHARS = 300

_IN_CHUNK = 200

VideoId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{11}$")]
_SENTENCE_END = re.compile(r"[.!?…\n]")


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class WatchStatus(BaseModel):
    indexed: bool  # in Langfour's index for the language, so it counts
    watched: bool


class DesktopWatch(BaseModel):
    video_id: VideoId
    language: Language
    share: float = Field(ge=WATCHED_SHARE, le=1)


class Unmark(BaseModel):
    video_id: VideoId


class HistoryItem(BaseModel):
    video_id: VideoId
    share: float | None = Field(default=None, ge=0, le=1)  # the red bar; None without one
    # Which section of the history page it was under: 0 today, 1 yesterday,
    # None for an earlier day.
    day: Literal[0, 1] | None = None


class HistoryRead(BaseModel):
    language: Language
    items: list[HistoryItem] = Field(max_length=HISTORY_ITEMS)


class HistoryKept(BaseModel):
    kept: int  # of the ids sent, how many are in the index and so stored


class WatchedVideo(BaseModel):
    video_id: str
    title: str | None
    watched_at: str
    source: str


class WatchedList(BaseModel):
    videos: list[WatchedVideo]  # newest first


class RecapWord(BaseModel):
    word_id: int
    word: str
    video_id: str  # the video it came up in most, where its sentence comes from


class Recap(BaseModel):
    day: date
    videos: int
    minutes: int
    words: list[RecapWord]  # empty: no recap


class RecapPick(BaseModel):
    word_id: int
    video_id: VideoId


class RecapAdd(BaseModel):
    language: Language
    words: list[RecapPick] = Field(min_length=1, max_length=RECAP_WORDS)


class RecapAdded(BaseModel):
    added: list[str]  # now in the user's list as learning


class RecapClose(BaseModel):
    day: date


# ---------------------------------------------------------------------------
# Transcripts: the processed JSON the recommender indexes, with every token's
# word id ("content") and the video's length in seconds.
# ---------------------------------------------------------------------------

def indexed(language: str, video_id: str) -> bool:
    return paths.processed_file(language, video_id).exists()


@lru_cache(maxsize=64)
def _read(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def transcript(language: str, video_id: str) -> dict | None:
    return _read(str(paths.processed_file(language, video_id)))


def word_ids(doc: dict) -> list[int]:
    """Every word id spoken, repeats included."""
    return [t["id"] for t in doc.get("content") or [] if isinstance(t.get("id"), int)]


def sentence_with(doc: dict, word_id: int) -> str | None:
    """A sentence of the transcript where the word comes up: the first of a
    good length, else the shortest. Auto-captions often have no punctuation,
    so a "sentence" can be the whole video; then the words around the first
    use stand in for it."""
    sentences: list[list[dict]] = [[]]
    for token in doc.get("content") or []:
        sentences[-1].append(token)
        if not isinstance(token.get("id"), int) and _SENTENCE_END.search(token.get("content") or ""):
            sentences.append([])

    def words(tokens: list[dict]) -> int:
        return sum(isinstance(t.get("id"), int) for t in tokens)

    found = [t for t in sentences if any(x.get("id") == word_id for x in t)]
    if not found:
        return None
    lo, hi = SENTENCE_WORDS
    good = [t for t in found if lo <= words(t) <= hi]
    best = good[0] if good else min(found, key=words)
    if words(best) > hi:
        at = next(i for i, t in enumerate(best) if t.get("id") == word_id)
        before = [i for i in range(at) if isinstance(best[i].get("id"), int)][-(hi // 2):]
        after = [i for i in range(at + 1, len(best)) if isinstance(best[i].get("id"), int)][:hi // 2]
        best = best[before[0] if before else at:(after[-1] if after else at) + 1]
    return " ".join("".join(t.get("content") or "" for t in best).split())[:MAX_SENTENCE_CHARS]


# ---------------------------------------------------------------------------
# Watch rows
# ---------------------------------------------------------------------------

def is_watched(row: dict) -> bool:
    """Not unmarked, and 70% played or the share unknown."""
    share = row.get("share")
    return row.get("unmarked_at") is None and (share is None or share >= WATCHED_SHARE)


def merge_desktop(row: dict | None, share: float, now: datetime) -> dict:
    """The fields to write for a desktop watch. It always marks: the user just
    played the video, after an unmark too."""
    old = row.get("share") if row and row.get("unmarked_at") is None else None
    return {"share": max(share, old or 0), "watched_at": now.isoformat(),
            "source": "desktop", "unmarked_at": None}


def merge_history(row: dict | None, item: HistoryItem, now: datetime) -> dict | None:
    """The fields to write for a video seen on the history page, or None to
    leave the row as it is."""
    when = (now - timedelta(days=item.day)).isoformat() if item.day is not None else None
    if row is None:
        return {"share": item.share, "watched_at": when, "source": "history", "unmarked_at": None}

    old = row.get("share")
    grew = item.share is not None and (old is None or item.share > old)
    if row.get("unmarked_at") is not None:
        # Unmarked: only a rewatch brings it back, which shows as a bar that
        # grew past 70% since.
        if (item.share is not None and item.share >= WATCHED_SHARE
                and (old is None or item.share >= old + REWATCH_GROWTH)):
            return {"share": item.share, "watched_at": when, "unmarked_at": None}
        return None
    if not grew:
        return None
    fields: dict = {"share": item.share}
    if not is_watched(row) and is_watched({**row, **fields}):
        fields["watched_at"] = when  # finished now: watched on this day
    return fields


# ---------------------------------------------------------------------------
# Storage. Like vocabulary.VocabularyStore: everything that touches Supabase
# is here, so the logic below runs against an in-memory stand-in in tests.
# ---------------------------------------------------------------------------

_COLUMNS = "video_id, language, watched_at, share, source, unmarked_at, created_at"


class WatchStore:
    def __init__(self, client):
        self.db = client
        self.vocab = VocabularyStore(client)

    def rows(self, user_id: str, video_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for chunk in _chunks(video_ids, _IN_CHUNK):
            res = (self.db.table("watch_events").select(_COLUMNS)
                   .eq("user_id", user_id).in_("video_id", chunk).execute())
            out.update({r["video_id"]: r for r in res.data or []})
        return out

    def write(self, user_id: str, language: str, video_id: str, fields: dict) -> None:
        (self.db.table("watch_events")
         .upsert({"user_id": user_id, "video_id": video_id, "language": language, **fields},
                 on_conflict="user_id,video_id")
         .execute())

    def unmark(self, user_id: str, video_id: str, now: datetime) -> None:
        (self.db.table("watch_events").update({"unmarked_at": now.isoformat()})
         .eq("user_id", user_id).eq("video_id", video_id).is_("unmarked_at", "null").execute())

    def delete_history(self, user_id: str) -> None:
        self.db.table("watch_events").delete().eq("user_id", user_id).eq("source", "history").execute()

    def watched_between(self, user_id: str, language: str, start: datetime, end: datetime) -> list[dict]:
        """Rows watched in [start, end), unmarked or not; the caller filters."""
        res = (self.db.table("watch_events").select(_COLUMNS)
               .eq("user_id", user_id).eq("language", language)
               .gte("watched_at", start.isoformat()).lt("watched_at", end.isoformat())
               .execute())
        return res.data or []

    def recent(self, user_id: str, language: str, limit: int) -> list[dict]:
        """The newest rows, unmarked or not; the caller filters."""
        res = (self.db.table("watch_events").select(_COLUMNS)
               .eq("user_id", user_id).eq("language", language).is_("unmarked_at", "null")
               .order("created_at", desc=True).limit(limit).execute())
        return res.data or []

    def valid_words(self, word_ids: list[int]) -> dict[int, str]:
        """word_id -> root for the ones that are vocabulary (status 'valid')."""
        out: dict[int, str] = {}
        for chunk in _chunks(word_ids, _IN_CHUNK):
            res = (self.db.table("words").select("id, root")
                   .eq("status", "valid").in_("id", chunk).execute())
            out.update({r["id"]: r["root"] for r in res.data or []})
        return out

    def closed_on(self, user_id: str) -> date | None:
        res = (self.db.table("userdata").select("watch_recap_closed_on")
               .eq("user_id", user_id).execute())
        value = (res.data or [{}])[0].get("watch_recap_closed_on")
        return date.fromisoformat(value) if value else None

    def close(self, user_id: str, day: date) -> None:
        (self.db.table("userdata").update({"watch_recap_closed_on": day.isoformat()})
         .eq("user_id", user_id).execute())


def get_watch_store() -> WatchStore:
    return WatchStore(supabase)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def status(store: WatchStore, user_id: str, language: str, video_id: str) -> WatchStatus:
    if not indexed(language, video_id):
        return WatchStatus(indexed=False, watched=False)
    row = store.rows(user_id, [video_id]).get(video_id)
    return WatchStatus(indexed=True, watched=bool(row) and is_watched(row))


def record_desktop(store: WatchStore, user_id: str, req: DesktopWatch) -> WatchStatus:
    if not indexed(req.language, req.video_id):
        return WatchStatus(indexed=False, watched=False)
    row = store.rows(user_id, [req.video_id]).get(req.video_id)
    store.write(user_id, req.language, req.video_id, merge_desktop(row, req.share, _now()))
    return WatchStatus(indexed=True, watched=True)


def unmark(store: WatchStore, user_id: str, req: Unmark) -> WatchStatus:
    store.unmark(user_id, req.video_id, _now())
    return WatchStatus(indexed=True, watched=False)


def record_history(store: WatchStore, user_id: str, req: HistoryRead) -> tuple[HistoryKept, list[str]]:
    """Stores the indexed ones. Also returns the videos that became watched
    today or yesterday, whose learning words count as heard."""
    items = {i.video_id: i for i in req.items if indexed(req.language, i.video_id)}
    rows = store.rows(user_id, list(items)) if items else {}
    now = _now()
    heard: list[str] = []
    for video_id, item in items.items():
        row = rows.get(video_id)
        fields = merge_history(row, item, now)
        if fields is None:
            continue
        store.write(user_id, req.language, video_id, fields)
        if (item.day is not None and is_watched({**(row or {}), **fields})
                and not (row and is_watched(row))):
            heard.append(video_id)
    return HistoryKept(kept=len(items)), heard


def record_heard(store: WatchStore, user_id: str, language: str, video_id: str) -> int:
    """The video's learning words as exposure, once per word per video, like
    caption words seen on desktop."""
    doc = transcript(language, video_id)
    if not doc:
        return 0
    ids = sorted(set(word_ids(doc)))
    statuses: dict[int, str] = {}
    for chunk in _chunks(ids, _IN_CHUNK):
        statuses.update(store.vocab.statuses(user_id, chunk))
    learning = [w for w in ids if statuses.get(w) == "learning"]
    if not learning:
        return 0
    req = SeenRequest(source="video", media=f"youtube:{video_id}",
                      word_ids=learning[:vocabulary.MAX_SEEN])
    return vocabulary.record_seen(store.vocab, user_id, req).recorded


def watched_list(store: WatchStore, user_id: str, language: str) -> WatchedList:
    rows = [r for r in store.recent(user_id, language, WATCHED_LIST) if is_watched(r)]
    rows.sort(key=lambda r: r.get("watched_at") or r["created_at"], reverse=True)
    return WatchedList(videos=[
        WatchedVideo(video_id=r["video_id"],
                     title=(transcript(language, r["video_id"]) or {}).get("title"),
                     watched_at=r.get("watched_at") or r["created_at"], source=r["source"])
        for r in rows
    ])


def _recap_rows(store: WatchStore, user_id: str, language: str,
                start: datetime, end: datetime) -> list[dict]:
    return [r for r in store.watched_between(user_id, language, start, end) if is_watched(r)]


def recap(store: WatchStore, user_id: str, language: str, day: date,
          start: datetime, end: datetime) -> Recap:
    """The recap of `day`, which ran from start to end in the user's time
    zone. Without words to offer, or put away with "Not now", it comes back
    with none and the clients show nothing."""
    empty = Recap(day=day, videos=0, minutes=0, words=[])
    if store.closed_on(user_id) == day:
        return empty
    rows = _recap_rows(store, user_id, language, start, end)
    if not rows:
        return empty

    seconds = 0.0
    times: Counter[int] = Counter()
    per_video: dict[int, Counter[str]] = {}
    for r in rows:
        doc = transcript(language, r["video_id"])
        if not doc:
            continue
        seconds += (doc.get("length") or 0) * (r.get("share") or 1)
        counts = Counter(word_ids(doc))
        times.update(counts)
        for w, n in counts.items():
            per_video.setdefault(w, Counter())[r["video_id"]] = n

    candidates = sorted(w for w, n in times.items()
                        if len(per_video[w]) >= RECAP_MIN_VIDEOS or n >= RECAP_MIN_TIMES)
    listed: dict[int, str] = {}
    for chunk in _chunks(candidates, _IN_CHUNK):
        listed.update(store.vocab.statuses(user_id, chunk))
    roots = store.valid_words([w for w in candidates if w not in listed])
    ranked = sorted(roots, key=lambda w: (-len(per_video[w]), -times[w], w))[:RECAP_WORDS]
    return Recap(
        day=day, videos=len(rows), minutes=round(seconds / 60),
        words=[RecapWord(word_id=w, word=roots[w], video_id=per_video[w].most_common(1)[0][0])
               for w in ranked],
    )


def add_recap_words(store: WatchStore, user_id: str, req: RecapAdd) -> RecapAdded:
    """Adds the words the user kept as learning, with the video as their
    source and a sentence from it as the context of a 'saved' event. Only
    words of videos the user watched, and only ones not in their list yet."""
    picks = {p.word_id: p.video_id for p in req.words}
    rows = store.rows(user_id, sorted(set(picks.values())))
    docs = {v: transcript(req.language, v) for v, r in rows.items() if is_watched(r)}
    picks = {w: v for w, v in picks.items() if docs.get(v) and w in set(word_ids(docs[v]))}
    listed = store.vocab.statuses(user_id, sorted(picks)) if picks else {}
    roots = store.valid_words([w for w in picks if w not in listed]) if picks else {}
    new = {w: v for w, v in picks.items() if w in roots}
    if not new:
        return RecapAdded(added=[])

    by_video: dict[str, list[int]] = {}
    for w, v in new.items():
        by_video.setdefault(v, []).append(w)
    for v, ids in by_video.items():
        store.vocab.add_words(user_id, sorted(ids), "learning", source=v)
    store.vocab.insert_events([
        {"user_id": user_id, "word_id": w, "kind": "saved", "source": "video",
         "context": {"site": "youtube", "media": f"youtube:{v}", "title": docs[v].get("title"),
                     "sentence": sentence_with(docs[v], w)}}
        for w, v in sorted(new.items())
    ])
    return RecapAdded(added=[roots[w] for w in sorted(new)])


def close_recap(store: WatchStore, user_id: str, req: RecapClose) -> None:
    store.close(user_id, req.day)


def turn_off_history(store: WatchStore, user_id: str) -> None:
    store.delete_history(user_id)
