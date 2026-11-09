"""
The web Videos page (docs/plans/home-redesign.md): the grid, its filters, what
to show when they leave nothing, Channels at your level, Not interested, and
what happened on YouTube since a card was opened.

  - grid: the recommendation order (video_blend.rank over the videos the
    learner hasn't watched), cut by topic, length, a search and grammar.
    Topics are the transcripts' categories, plus Following: the videos of the
    channels the learner made a favourite on YouTube (channels.py).
  - grammar: video_scores.grammar puts A1..C1 at 1, 3, 5, 7, 9; a video's
    level is the nearest one, cutting halfway between. "Up to B1" keeps
    A1..B1. A video without a score has no level, so it is left out while the
    filter is on and is not counted.
  - levels: how many videos each level has in the current topic, length and
    search, whatever the grammar filter. None for a language without scores,
    where the page offers no grammar filter.
  - empty: when the grammar filter leaves nothing in a topic, the nearest
    level above it that has videos, the topic's videos up to that level, and
    the other topics' videos up to the filter's level.
  - channels: on All or a topic, without a search, CHANNELS channels worth
    following (the page shows CHANNEL_PAGE at a time), as video_blend ranks
    videos: the CHANNEL_POOL best understood
    (by share of all their unwatched speech, as channels.py computes
    "understood"), then reordered by a weighted geometric mean of
    percentiles of understood, the judge's interest, clean (-trash) and text
    scores averaged over each channel's judged videos, and, when the learner
    has seeds, similar: how alike the channel is to them in what it talks
    about (channel_similarity.py).
    Seeds are the channels they made a favourite (all their videos) and the
    channels of the videos they watched (those videos; watch_events, which
    the extension also fills from their YouTube history). A channel's
    similar is its best lift over the seeds: how many standard deviations
    its cosine with the seed sits above that seed's mean over every
    eligible channel, times the seed's strength (a favourite 1, a channel
    watched once WATCHED_SEED). Raw cosines would make a big, broad channel
    every channel's nearest seed, and lifts within one topic would make the
    closest gaming channel to a self-help video look like a match. From
    BECAUSE_LIFT that seed is the channel's `because`. With seeds the pool
    is CHANNEL_POOL_SEEDED, so channels like them get in. Each CHANNEL_PAGE
    first takes at most one channel per nearest seed, so two favourites both
    get a place. Channels they follow or watched are not suggested: the
    section is for finding new ones. On a topic, the channels that cover it
    often compete (TOPIC_MIN_VIDEOS videos in it, and TOPIC_MIN_SHARE of the
    channel's categorised videos), counted and shown by those videos alone,
    and the more of a channel is about the topic the better (`covers`).
    `basis` says what the picks rest on, so the page can say so or, with
    nothing, say how to give it something.
    A channel more than CHANNEL_MAX_REJECTED of whose judged videos the
    judge rejects is left out: clickbait channels get most videos through
    one at a time. Its videos are its first SHELF in the grid's order. A
    channel is its transcripts' creator name; its UC id, for Follow, comes
    from video_queue.
  - hides: Not interested and "Hide all from <channel>" (sql/video_hides.sql).
    Only this grid leaves them out.
  - return: when the learner comes back from YouTube, how far into the video
    they got (watch_events.share) and how many words they saved from it
    (word_events 'saved' whose context names the video; the extension writes
    that context for words saved on a YouTube watch page).
  - reuse: everything read and scored for a learner is kept for VISIT_TTL. A
    request with reuse (the page's next topic or filter) answers from it; one
    without (opening the page, coming back from YouTube, after a Follow)
    reads it all again. Reads were most of a topic switch: 0.5 of 0.8 s, and
    the channel similarities most of the rest.

Coverage counts every word spoken, as the recommender's percentages do.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel

import channel_similarity
import video_blend
from recommender import MIN_DISTINCT_WORDS
from vocabulary import Language
from watch import WATCHED_SHARE, VideoId, is_watched

log = logging.getLogger(__name__)

ALL = "All"
FOLLOWING = "Following"
LEVELS = ("A1", "A2", "B1", "B2", "C1")
Level = Literal["A1", "A2", "B1", "B2", "C1"]
# Seconds; a video without a length only shows under "any".
LENGTHS: dict[str, tuple[float, float]] = {
    "any": (0, float("inf")),
    "short": (0, 10 * 60),
    "medium": (10 * 60, 20 * 60),
    "long": (20 * 60, float("inf")),
}
Length = Literal["any", "short", "medium", "long"]
GRID = 48             # cards sent; the page shows 12 at a time
SHELF = 4             # cards in a row of the empty state or a channel
CHANNELS = 15          # sent; the page shows CHANNEL_PAGE at a time
CHANNEL_PAGE = 3
CHANNEL_MIN_VIDEOS = 4
TOPIC_MIN_VIDEOS = 3   # to count as covering a topic
TOPIC_MIN_SHARE = 0.25 # of the channel's videos that have a category
CHANNEL_POOL = 0.3            # share of the eligible channels, best understood first
CHANNEL_POOL_SEEDED = 0.6     # the same with seeds, so channels like them get in
CHANNEL_POOL_MIN = CHANNELS
CHANNEL_MAX_REJECTED = 0.2
CHANNEL_WEIGHTS = {"understood": 0.3, "interest": 0.3, "clean": 0.2, "text": 0.2}
SIMILAR_WEIGHT = 1.5          # with seeds: 1.5 of 2.5 of the score
COVERS_WEIGHT = 0.5           # on a topic: how much of the channel is about it
MAX_WATCHED_SEEDS = 20        # channels, most watched first
BECAUSE_LIFT = 2.0            # standard deviations above the seed's mean cosine
WATCHED_SEED = 0.6            # a watched channel's weight against a favourite's 1,
WATCHED_SEED_STEP = 0.2       # plus this per watched video after the first
VISIT_TTL = 300               # seconds
VISITS_KEPT = 8               # learners; each holds ~1-2 MB

_PAGE = 1000          # PostgREST's row cap per request
_IN_CHUNK = 200


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class HomeVideo(BaseModel):
    id: str
    title: str
    channel: str | None
    duration_s: int | None
    understood: float            # % of the speech the learner knows
    new_words: int               # distinct words they don't
    watched_share: float | None  # played so far, for a video started and not finished


class Shelf(BaseModel):
    count: int
    videos: list[HomeVideo]


class Empty(BaseModel):
    nearest_level: Level | None  # the first level above the filter with videos
    nearest: Shelf | None        # the topic up to nearest_level
    other: Shelf | None          # every other topic up to the filter's level


class HomeChannel(BaseModel):
    name: str
    channel_id: str | None       # None when video_queue doesn't know it: no Follow
    following: bool
    understood: float
    videos: int                  # unwatched videos of the channel in the index
    best: list[HomeVideo]
    because: str | None = None   # the followed or watched channel it is most like


class ChannelBasis(BaseModel):
    following: list[str]         # names of the favourite channels in the index
    watched: int                 # videos watched (or started) from the index


class Home(BaseModel):
    videos: list[HomeVideo]
    total: int
    topics: list[str]
    levels: dict[Level, int] | None
    empty: Empty | None
    channels: list[HomeChannel]
    basis: ChannelBasis | None   # what channels rests on; None when it isn't shown


class HideRequest(BaseModel):
    language: Language
    video_id: VideoId
    channel: bool = False        # the video's whole channel rather than the video


class Hidden(BaseModel):
    channel: str | None          # the name hidden or shown again, with channel


class Return(BaseModel):
    share: float | None
    saved: int


# ---------------------------------------------------------------------------
# Storage. Like channels.ChannelStore: everything that touches Supabase is
# here, so the logic below runs against an in-memory stand-in in tests.
# ---------------------------------------------------------------------------

def _chunks(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


class HomeStore:
    def __init__(self, client):
        self.db = client

    def _paged(self, query) -> list[dict]:
        out: list[dict] = []
        while True:
            rows = query().range(len(out), len(out) + _PAGE - 1).execute().data or []
            out += rows
            if len(rows) < _PAGE:
                return out

    def known_words(self, user_id: str) -> set[int]:
        """As Recommender.get_known_words: declared known or learned in reviews."""
        return {r["word_id"] for r in self._paged(
            lambda: self.db.table("user_known_words").select("word_id")
            .eq("user_id", user_id).order("word_id"))}

    def watch_rows(self, user_id: str) -> dict[str, dict]:
        """video_id -> {share, unmarked_at} for every video the user started."""
        return {r["video_id"]: r for r in self._paged(
            lambda: self.db.table("watch_events").select("video_id,share,unmarked_at")
            .eq("user_id", user_id).order("id"))}

    def watch_row(self, user_id: str, video_id: str) -> dict | None:
        rows = (self.db.table("watch_events").select("video_id,share,unmarked_at")
                .eq("user_id", user_id).eq("video_id", video_id).limit(1).execute().data)
        return rows[0] if rows else None

    def hides(self, user_id: str, language: str) -> tuple[set[str], set[str]]:
        """(video ids, channel names) hidden. Nothing before video_hides.sql
        is applied, rather than a page that won't load."""
        try:
            rows = self._paged(lambda: self.db.table("video_hides").select("kind,key")
                               .eq("user_id", user_id).eq("language", language)
                               .order("created_at"))
        except Exception:
            log.warning("Could not read video_hides; hiding nothing", exc_info=True)
            return set(), set()
        return ({r["key"] for r in rows if r["kind"] == "video"},
                {r["key"] for r in rows if r["kind"] == "channel"})

    def hide(self, user_id: str, language: str, kind: str, key: str) -> None:
        (self.db.table("video_hides")
         .upsert({"user_id": user_id, "language": language, "kind": kind, "key": key},
                 on_conflict="user_id,language,kind,key", ignore_duplicates=True)
         .execute())

    def unhide(self, user_id: str, language: str, kind: str, key: str) -> None:
        (self.db.table("video_hides").delete().eq("user_id", user_id)
         .eq("language", language).eq("kind", kind).eq("key", key).execute())

    def favourites(self, user_id: str, language: str) -> set[str]:
        """UC ids of the channels the user made a favourite in this language."""
        res = (self.db.table("channel_favourites").select("channel_id")
               .eq("user_id", user_id).eq("lang", language).execute())
        return {r["channel_id"] for r in res.data or []}

    def videos_of(self, channel_ids: set[str], language: str) -> set[str]:
        """The indexed videos of these channels."""
        out: set[str] = set()
        for chunk in _chunks(sorted(channel_ids), _IN_CHUNK):
            out |= {r["video_id"] for r in self._paged(
                lambda chunk=chunk: self.db.table("video_queue").select("video_id")
                .in_("channel_id", chunk).eq("lang", language).eq("status", "done")
                .order("video_id"))}
        return out

    def channel_ids(self, video_ids: list[str]) -> dict[str, str]:
        """video_id -> UC id, for the ones video_queue has."""
        out: dict[str, str] = {}
        for chunk in _chunks(video_ids, _IN_CHUNK):
            res = (self.db.table("video_queue").select("video_id,channel_id")
                   .in_("video_id", chunk).execute())
            out |= {r["video_id"]: r["channel_id"] for r in res.data or [] if r.get("channel_id")}
        return out

    def saved_since(self, user_id: str, video_id: str, since: datetime) -> int:
        """Distinct words saved from this video since `since`."""
        res = (self.db.table("word_events").select("word_id")
               .eq("user_id", user_id).eq("kind", "saved")
               .eq("context->>media", f"youtube:{video_id}")
               .gte("occurred_at", since.isoformat()).execute())
        return len({r["word_id"] for r in res.data or []})


def get_home_store() -> HomeStore:
    from supabase_client import supabase
    return HomeStore(supabase)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def level_of(grammar: float | None) -> int | None:
    """Index into LEVELS of a video_scores.grammar value (A1..C1 at 1..9)."""
    if grammar is None:
        return None
    return min(len(LEVELS) - 1, max(0, int(grammar // 2)))


class _Corpus:
    """One request's view of a language: who the videos are for this learner."""

    def __init__(self, recommender, language: str, known: set[int], watch: dict[str, dict],
                 hidden_videos: set[str], hidden_channels: set[str]):
        # Every array below comes from this one index, so rows line up.
        self.index = index = recommender.index(language)
        self.language = language
        self.rows = index.rows
        self.titles = index.titles
        self.categories = index.categories
        self.creators = index.creators
        self.lengths = index.lengths
        self.grammar = recommender.grammar.get(language) or {}
        self.spoken = index.spoken
        self.signals = recommender.video_signals.get(language) or {}
        self.watch = watch
        self.ratios, self.new_words, _ = index.score(known)

        distinct = index.distinct
        candidates = [
            (video_id, float(self.ratios[row])) for video_id, row in self.rows.items()
            if video_id not in recommender.hidden_videos
            and distinct[row] >= MIN_DISTINCT_WORDS
            and not (video_id in watch and is_watched(watch[video_id]))
            and video_id not in hidden_videos
            and self.creators[row] not in hidden_channels
        ]
        candidates.sort(key=lambda c: -c[1])
        # video_blend drops the videos whose thumbnails it rejects.
        self.ordered = (video_blend.rank(candidates, self.signals) if self.signals
                        else [video_id for video_id, _ in candidates])

    def level(self, video_id: str) -> int | None:
        return level_of(self.grammar.get(video_id))

    def card(self, video_id: str) -> HomeVideo:
        row = self.rows[video_id]
        played = self.watch.get(video_id) or {}
        share = played.get("share") if played.get("unmarked_at") is None else None
        return HomeVideo(
            id=video_id,
            title=self.titles[row] or video_id,
            channel=self.creators[row] or None,
            duration_s=self.lengths[row],
            understood=round(float(self.ratios[row]) * 100, 1),
            new_words=int(self.new_words[row]),
            watched_share=share if share and share < WATCHED_SHARE else None,
        )

    def shelf(self, video_ids: list[str]) -> Shelf | None:
        if not video_ids:
            return None
        return Shelf(count=len(video_ids), videos=[self.card(v) for v in video_ids[:SHELF]])


def _filtered(corpus: _Corpus, topic: str, followed: set[str], length: str,
              query: str) -> list[str]:
    low, high = LENGTHS[length]
    needle = query.casefold().strip()

    def keep(video_id: str) -> bool:
        row = corpus.rows[video_id]
        if topic == FOLLOWING:
            if video_id not in followed:
                return False
        elif topic != ALL and corpus.categories[row] != topic:
            return False
        if length != "any":
            seconds = corpus.lengths[row]
            if seconds is None or not low <= seconds < high:
                return False
        return (not needle or needle in (corpus.titles[row] or "").casefold()
                or needle in corpus.creators[row].casefold())

    return [v for v in corpus.ordered if keep(v)]


def _up_to(corpus: _Corpus, video_ids: list[str], level: int) -> list[str]:
    return [v for v in video_ids if (lv := corpus.level(v)) is not None and lv <= level]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _channel_signals(corpus: _Corpus) -> dict[str, dict[str, float | None]]:
    """Per channel name, over every judged video of it, watched and rejected
    ones too: the share rejected and the mean interest, clean and text."""
    looks: dict[str, list[dict]] = defaultdict(list)
    texts: dict[str, list[float]] = defaultdict(list)
    for video_id, row in corpus.rows.items():
        name = corpus.creators[row]
        signal = corpus.signals.get(video_id)
        if not name or not signal:
            continue
        if signal.get("look"):
            looks[name].append(signal["look"])
        if signal.get("text") is not None:
            texts[name].append(signal["text"])
    return {name: {
        "rejected": (sum(1 for look in looks[name] if video_blend.rejected(look)) / len(looks[name])
                     if looks[name] else None),
        "interest": _mean([look["interest"] for look in looks[name]]),
        "clean": _mean([-look["trash"] for look in looks[name]]),
        "text": _mean(texts[name]),
    } for name in looks.keys() | texts.keys()}


def _has_category(category: str | None) -> bool:
    return bool(category) and category.strip().lower() not in ("failed", "unknown")


def _seeds(corpus: _Corpus, favourite_names: set[str]) -> list[tuple[str, list[int]]]:
    """(name, matrix rows) per seed: each favourite channel with all its
    videos, then the channels of the videos watched, with those videos."""
    rows_of: dict[str, list[int]] = defaultdict(list)
    for row, name in enumerate(corpus.creators):
        if name in favourite_names:
            rows_of[name].append(row)
    seeds = [(name, rows_of[name]) for name in sorted(favourite_names) if rows_of[name]]
    watched: dict[str, list[int]] = defaultdict(list)
    for video_id, played in corpus.watch.items():
        row = corpus.rows.get(video_id)
        if row is None or played.get("unmarked_at") is not None:
            continue
        name = corpus.creators[row]
        if name and name not in favourite_names:
            watched[name].append(row)
    most = sorted(watched.items(), key=lambda item: (-len(item[1]), item[0]))
    return seeds + most[:MAX_WATCHED_SEEDS]


def _basis(corpus: _Corpus, favourite_names: set[str]) -> ChannelBasis:
    return ChannelBasis(
        following=sorted(favourite_names),
        watched=sum(1 for video_id, played in corpus.watch.items()
                    if video_id in corpus.rows and played.get("unmarked_at") is None),
    )


class _Candidates:
    """The channels that can be suggested to this learner, on any topic."""

    def __init__(self, recommender, corpus: _Corpus, favourite_names: set[str]):
        seeds = _seeds(corpus, favourite_names)
        known = favourite_names | {name for name, _ in seeds}
        by_channel: dict[str, list[str]] = defaultdict(list)
        for video_id in corpus.ordered:
            name = corpus.creators[corpus.rows[video_id]]
            if name and name not in known:
                by_channel[name].append(video_id)
        self.seeded = bool(seeds)
        self.signals = _channel_signals(corpus)
        self.eligible = {name: video_ids for name, video_ids in by_channel.items()
                         if len(video_ids) >= CHANNEL_MIN_VIDEOS
                         and (self.signals.get(name, {}).get("rejected") or 0) <= CHANNEL_MAX_REJECTED}

        # Against every channel, not one topic's: how alike a channel is to a
        # seed is judged against them all, or the closest gaming channel to a
        # self-help video would look like a match.
        self.similar: dict[str, float] = {}
        self.seed_of: dict[str, str] = {}
        self.because: dict[str, str] = {}
        if seeds and self.eligible:
            names = list(self.eligible)
            cosines = channel_similarity.channel_cosines(
                corpus.index, names, [rows for _, rows in seeds])
            # Relative to how alike the seed is to every channel: a big, broad
            # channel is fairly close to everything and would be every channel's
            # nearest seed by raw cosine.
            spread = cosines.std(axis=0)
            lift = (cosines - cosines.mean(axis=0)) / np.where(spread > 0, spread, 1)
            # A favourite counts in full, a channel watched once a little less.
            strength = np.array([1.0 if name in favourite_names
                                 else min(1.0, WATCHED_SEED + WATCHED_SEED_STEP * (len(rows) - 1))
                                 for name, rows in seeds])
            weighed = lift * strength
            for i, j in enumerate(weighed.argmax(axis=1)):
                self.similar[names[i]] = float(weighed[i, j])
                self.seed_of[names[i]] = seeds[j][0]
                if weighed[i, j] >= BECAUSE_LIFT:
                    self.because[names[i]] = seeds[j][0]


def _spread_over_seeds(order: list[int], seed_of: list[str | None]) -> list[int]:
    """CHANNELS of `order`, a CHANNEL_PAGE at a time, each page taking one
    channel per seed before a second, so one favourite doesn't fill it."""
    left, out = list(order), []
    rank = {i: place for place, i in enumerate(order)}
    while left and len(out) < CHANNELS:
        page: list[int] = []
        used: set[str] = set()
        for i in left:
            seed = seed_of[i]
            if len(page) < CHANNEL_PAGE and (seed is None or seed not in used):
                page.append(i)
                if seed:
                    used.add(seed)
        page += [i for i in left if i not in page][:CHANNEL_PAGE - len(page)]
        out += sorted(page, key=rank.__getitem__)
        left = [i for i in left if i not in page]
    return out[:CHANNELS]


def _channels(store: HomeStore, corpus: _Corpus, found: _Candidates, favourites: set[str],
              topic: str = ALL) -> list[HomeChannel]:
    candidates = []
    covers: dict[str, float] = {}
    for name, video_ids in found.eligible.items():
        if topic != ALL:
            categories = [corpus.categories[corpus.rows[v]] for v in video_ids]
            in_topic = [v for v, category in zip(video_ids, categories, strict=True)
                        if category == topic]
            categorised = sum(1 for category in categories if _has_category(category))
            if (len(in_topic) < TOPIC_MIN_VIDEOS
                    or len(in_topic) / max(categorised, 1) < TOPIC_MIN_SHARE):
                continue
            covers[name] = len(in_topic) / max(categorised, 1)
            video_ids = in_topic
        rows = [corpus.rows[v] for v in video_ids]
        spoken = corpus.spoken[rows]
        if not spoken.sum():
            continue
        understood = float((corpus.ratios[rows] * spoken).sum() / spoken.sum())
        candidates.append((understood, len(video_ids), name, video_ids))
    candidates.sort(key=lambda s: (-s[0], -s[1], s[2]))
    share = CHANNEL_POOL_SEEDED if found.seeded else CHANNEL_POOL
    pool = candidates[:max(CHANNEL_POOL_MIN, int(len(candidates) * share))]
    if not pool:
        return []

    columns: dict[str, list[float | None]] = {
        "understood": [understood for understood, *_ in pool],
        **{key: [found.signals.get(name, {}).get(key) for _, _, name, _ in pool]
           for key in ("interest", "clean", "text")},
    }
    weights = dict(CHANNEL_WEIGHTS)
    if found.similar:
        columns["similar"] = [found.similar.get(name) for _, _, name, _ in pool]
        weights["similar"] = SIMILAR_WEIGHT
    if covers:
        columns["covers"] = [covers.get(name) for _, _, name, _ in pool]
        weights["covers"] = COVERS_WEIGHT

    scores = [1.0] * len(pool)
    for key, weight in weights.items():
        for i, p in enumerate(video_blend.percentiles(columns[key])):
            scores[i] *= max(p, video_blend.MIN_PERCENTILE) ** weight
    # Stable: ties keep the understood order.
    order = sorted(range(len(pool)), key=lambda i: -scores[i])
    picked = _spread_over_seeds(order, [found.seed_of.get(name) for _, _, name, _ in pool])
    chosen = [pool[i] for i in picked]

    best_videos = {name: video_ids[:SHELF] for _, _, name, video_ids in chosen}
    ids = store.channel_ids([v for videos in best_videos.values() for v in videos])
    out = []
    for understood, count, name, _ in chosen:
        channel_id = next((ids[v] for v in best_videos[name] if v in ids), None)
        out.append(HomeChannel(
            name=name, channel_id=channel_id, following=channel_id in favourites,
            understood=round(understood * 100, 1), videos=count,
            best=[corpus.card(v) for v in best_videos[name]], because=found.because.get(name),
        ))
    return out


class _Visit:
    """What one request needs to know about a learner, kept for the next
    topic. The channels are worked out when first asked for, per topic."""

    def __init__(self, store: HomeStore, recommender, user_id: str, language: str):
        hidden_videos, hidden_channels = store.hides(user_id, language)
        self.corpus = _Corpus(recommender, language, store.known_words(user_id),
                              store.watch_rows(user_id), hidden_videos, hidden_channels)
        self.favourites = store.favourites(user_id, language)
        self.followed = store.videos_of(self.favourites, language) if self.favourites else set()
        self.favourite_names = {name for v in self.followed
                                if (row := self.corpus.rows.get(v)) is not None
                                and (name := self.corpus.creators[row])}
        self.recommender = recommender
        self.built = time.monotonic()
        self._candidates: _Candidates | None = None
        self._channels: dict[str, list[HomeChannel]] = {}

    def current(self, recommender, language: str) -> bool:
        """Not too old, and the corpus it was scored on is still the live one."""
        return (time.monotonic() - self.built < VISIT_TTL
                and self.corpus.index is recommender.index(language))

    def channels(self, store: HomeStore, topic: str) -> list[HomeChannel]:
        if topic not in self._channels:
            if self._candidates is None:
                self._candidates = _Candidates(self.recommender, self.corpus, self.favourite_names)
            self._channels[topic] = _channels(store, self.corpus, self._candidates,
                                              self.favourites, topic)
        return self._channels[topic]


_visits: OrderedDict[tuple[str, str], _Visit] = OrderedDict()
_visits_lock = threading.Lock()


def _visit(store: HomeStore, recommender, user_id: str, language: str, reuse: bool) -> _Visit:
    key = (user_id, language)
    if reuse:
        with _visits_lock:
            visit = _visits.get(key)
            if visit is not None:
                _visits.move_to_end(key)
        if visit is not None and visit.current(recommender, language):
            return visit
    visit = _Visit(store, recommender, user_id, language)
    with _visits_lock:
        _visits[key] = visit
        _visits.move_to_end(key)
        while len(_visits) > VISITS_KEPT:
            _visits.popitem(last=False)
    return visit


def home(store: HomeStore, recommender, user_id: str, language: str, topic: str = ALL,
         grammar: Level | None = None, length: Length = "any", query: str = "",
         reuse: bool = False) -> Home:
    visit = _visit(store, recommender, user_id, language, reuse)
    corpus = visit.corpus
    with_channels = topic != FOLLOWING and not query.strip()
    pool = _filtered(corpus, topic, visit.followed, length, query)

    levels = None
    if corpus.grammar:
        counts = np.bincount([lv for v in pool if (lv := corpus.level(v)) is not None],
                             minlength=len(LEVELS))
        levels = {name: int(counts[i]) for i, name in enumerate(LEVELS)}

    shown, empty = pool, None
    if grammar is not None and levels is not None:
        cut = LEVELS.index(grammar)
        shown = _up_to(corpus, pool, cut)
        if not shown:
            above = [i for i in range(cut + 1, len(LEVELS)) if levels[LEVELS[i]]]
            nearest = above[0] if above else None
            other = []
            if topic != ALL:
                in_topic = set(pool)
                other = [v for v in _up_to(corpus, _filtered(corpus, ALL, set(), length, query), cut)
                         if v not in in_topic]
            empty = Empty(
                nearest_level=LEVELS[nearest] if nearest is not None else None,
                nearest=corpus.shelf(_up_to(corpus, pool, nearest)) if nearest is not None else None,
                other=corpus.shelf(other),
            )

    return Home(
        videos=[corpus.card(v) for v in shown[:GRID]],
        total=len(shown),
        # As the old grid did: "Failed" is an ingest outcome, not a topic.
        topics=[c["category"] for c in recommender.get_categories(language)
                if _has_category(c["category"])],
        levels=levels,
        empty=empty,
        channels=visit.channels(store, topic) if with_channels else [],
        basis=_basis(corpus, visit.favourite_names) if with_channels else None,
    )


def _channel_of(recommender, language: str, video_id: str) -> str | None:
    index = recommender.index(language)
    row = index.rows.get(video_id)
    return (index.creators[row] or None) if row is not None else None


def set_hidden(store: HomeStore, recommender, user_id: str, req: HideRequest,
               hidden: bool) -> Hidden:
    """Hide, or show again, a video or its channel. A channel is named by one
    of its videos, as the card that asks has only that."""
    if req.channel:
        name = _channel_of(recommender, req.language, req.video_id)
        if name is None:
            return Hidden(channel=None)
        kind, key = "channel", name
    else:
        kind, key, name = "video", req.video_id, None
    (store.hide if hidden else store.unhide)(user_id, req.language, kind, key)
    return Hidden(channel=name)


def came_back(store: HomeStore, user_id: str, video_id: str, since: datetime) -> Return:
    row = store.watch_row(user_id, video_id)
    share = row.get("share") if row and row.get("unmarked_at") is None else None
    return Return(share=share, saved=store.saved_since(user_id, video_id, since))
