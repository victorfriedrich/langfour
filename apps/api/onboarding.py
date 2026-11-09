"""Onboarding before there is an account, and the daily words after.

The preview answers what a level and some topics open up: the Videos page's
own order (home._Corpus) worked out from that level's starting words, and how
many of the chosen topics' videos a daily pace of new words gets to 90% in two
weeks. It needs no account, so the get-started page can show it while the
learner is still choosing.

Daily words are the words a learner gets each day: picked from their topics,
most widespread first (as Add common words ranks them), valid dictionary words
only, never one they know or have already saved. The web adds them to the
review queue itself, through the same RPC every other word takes.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterable
from typing import Literal

import numpy as np
from pydantic import BaseModel

import home
from home import HomeVideo
from recommender import MIN_DISTINCT_WORDS

StartLevel = Literal["A1", "A2", "B1", "B2"]

PACES = (10, 15, 25)         # words a day the learner can choose from
DAYS = 14                    # what "in two weeks" means
AT_YOUR_LEVEL = 0.90         # the share of known words a video counts as followable at
PREVIEW = 12                 # videos shown beside the level and topic steps
CANDIDATES = 400             # words looked at per topic before validity filtering
MAX_TOPICS = 20
MAX_DAILY = 50
_IN_CHUNK = 500              # ids per PostgREST `in` filter
_PAGE = 1000                 # PostgREST's row cap


class Preview(BaseModel):
    level: StartLevel
    words: int                    # starting words the level marks as known
    topics: list[str]             # every topic there is to pick
    videos: list[HomeVideo]       # the Videos page's first cards for this level and topics
    now: int                      # the topics' videos at 90%+ today
    pace: dict[int, int]          # ... after DAYS at that many new words a day


class DailyWords(BaseModel):
    word_ids: list[int]


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


class OnboardingStore:
    """The two things onboarding reads from Supabase, both kept in memory:
    a level's starting words never change between deploys, and a word's
    dictionary status changes rarely enough for a process lifetime."""

    def __init__(self, db):
        self.db = db
        self._levels: dict[tuple[str, str], set[int]] = {}
        self._status: dict[int, bool] = {}
        self._lock = threading.Lock()

    def level_words(self, language: str, level: str) -> set[int]:
        key = (language, level)
        with self._lock:
            cached = self._levels.get(key)
        if cached is not None:
            return cached
        words: set[int] = set()
        offset = 0
        while True:
            res = (self.db.table("languagelevels").select("word_id")
                   .eq("language", language).eq("language_level", level)
                   .order("id").range(offset, offset + _PAGE - 1).execute())
            rows = res.data or []
            words |= {int(r["word_id"]) for r in rows}
            if len(rows) < _PAGE:
                break
            offset += _PAGE
        with self._lock:
            self._levels[key] = words
        return words

    def valid(self, word_ids: list[int]) -> set[int]:
        """The ones the dictionary review kept."""
        with self._lock:
            missing = [w for w in word_ids if w not in self._status]
        found: set[int] = set()
        for chunk in _chunks(missing, _IN_CHUNK):
            res = (self.db.table("words").select("id").in_("id", chunk)
                   .eq("status", "valid").execute())
            found |= {int(r["id"]) for r in res.data or []}
        with self._lock:
            for w in missing:
                self._status[w] = w in found
            return {w for w in word_ids if self._status.get(w)}


_store: OnboardingStore | None = None


def get_onboarding_store() -> OnboardingStore:
    global _store
    if _store is None:
        from supabase_client import supabase
        _store = OnboardingStore(supabase)
    return _store


def picks(store: OnboardingStore, recommender, language: str, known: set[int],
          topics: list[str], n: int) -> list[int]:
    """The next `n` words to learn: each topic's words in the most videos
    first, taken in turn so every chosen topic gets its share."""
    lists = []
    for topic in topics or [None]:
        ranked = recommender.recommend_words_to_learn(
            language=language, known_word_ids=list(known),
            filter_category=topic, n_words=CANDIDATES)
        lists.append([r["word_id"] for r in ranked])
    merged: list[int] = []
    seen: set[int] = set()
    for i in range(CANDIDATES):
        for ranked in lists:
            if i < len(ranked) and ranked[i] not in seen:
                seen.add(ranked[i])
                merged.append(ranked[i])
    valid = store.valid(merged)
    return [w for w in merged if w in valid][:n]


def _rows(recommender, language: str, topics: list[str]) -> list[int]:
    """The videos a learner could be recommended in those topics (all, without)."""
    cats = recommender.categories[language]
    files = recommender.filenames[language]
    distinct = recommender.distinct_words_per_doc[language]
    chosen = set(topics)
    return [i for i, cat in enumerate(cats)
            if (not chosen or cat in chosen)
            and distinct[i] >= MIN_DISTINCT_WORDS
            and files[i].replace("_processed.json", "") not in recommender.hidden_videos]


def _at_your_level(recommender, language: str, words: set[int], rows: list[int]) -> int:
    if not rows:
        return 0
    ratios, _, _ = recommender._score_documents_by_words(
        list(words), language, distinct=False, rows=rows)
    return int((np.asarray(ratios) >= AT_YOUR_LEVEL).sum())


def topics_of(recommender, language: str) -> list[str]:
    return [c["category"] for c in recommender.get_categories(language)
            if home._has_category(c["category"])]


_previews: OrderedDict[tuple, Preview] = OrderedDict()
_previews_lock = threading.Lock()
PREVIEWS_KEPT = 256


def preview(store: OnboardingStore, recommender, language: str, level: StartLevel,
            topics: list[str]) -> Preview:
    recommender._ensure_language_loaded(language)
    topics = sorted(set(topics))
    # Keyed on the matrix too, so a reload of the corpus is never answered
    # from before it.
    key = (language, level, tuple(topics), id(recommender.matrices[language]))
    with _previews_lock:
        cached = _previews.get(key)
        if cached is not None:
            _previews.move_to_end(key)
            return cached

    known = store.level_words(language, level)
    corpus = home._Corpus(recommender, language, known, {}, set(), set())
    chosen = set(topics)
    ordered = [v for v in corpus.ordered
               if not chosen or corpus.categories[corpus.rows[v]] in chosen]
    rows = _rows(recommender, language, topics)
    ahead = picks(store, recommender, language, known, topics, max(PACES) * DAYS)
    result = Preview(
        level=level,
        words=len(known),
        topics=topics_of(recommender, language),
        videos=[corpus.card(v) for v in ordered[:PREVIEW]],
        now=_at_your_level(recommender, language, known, rows),
        pace={p: _at_your_level(recommender, language, known | set(ahead[:p * DAYS]), rows)
              for p in PACES},
    )
    with _previews_lock:
        _previews[key] = result
        while len(_previews) > PREVIEWS_KEPT:
            _previews.popitem(last=False)
    return result


def daily_words(store: OnboardingStore, recommender, language: str, known: set[int],
                saved: set[int], topics: list[str], n: int) -> DailyWords:
    recommender._ensure_language_loaded(language)
    return DailyWords(word_ids=picks(store, recommender, language, known | saved,
                                     sorted(set(topics)), n))
