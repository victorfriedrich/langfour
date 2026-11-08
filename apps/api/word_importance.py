"""Which words of a video or Library item matter most, ranked once with Jev.

The missing-words list used to be every unknown word of the text, in no order
of importance. Jev now scores each word of the text on two 1..5 scales:

  here      how relevant it is to understanding this text: how often it occurs,
            in which lines, and how much a learner without it would miss
  general   how relevant it is to learning the language at all: everyday
            frequency; names, interjections and niche jargon score low

Every word of the text is ranked, not just the ones the user is missing, so
the result is the same for every user and is computed once: on the first
open of the list, then saved (video_word_ranks for the shared corpus,
user_media.word_ranks for a Library item; sql/word_ranks.sql). Both scales
are saved, and KEY_FROM / MAX_KEY_WORDS live here, so how they combine can
be re-tuned without new requests.

All words go in one request: the text, the rubric and the word list once in
the state, and one short question per scale and word that points at them.
Writing the rubric into every question was refused as too long at this size.
A 4,050-word episode with 709 words took one request and about 3 s. About 800
words fit beside a text that short and 500 beside a 48,000-word one, so a
request Jev refuses as too long is split in two rather than sized in advance.

Basic words score high on purpose (que 4.87, ser 4.86 on that episode): they
matter to the language and to the text. A learner who knows them never sees
them, because only their missing words are listed. For a user missing 203 of
those 709 words the list starts el jugador, el cuervo, el funeral, la presidencia
and ends el nogal, timar, la antártica, el maní.

Ranking never breaks the list: if Jev or the table fails, the words come
back unranked and the next open tries again.

The list doesn't wait for Jev either. The endpoints pass wait=False: saved
ranks come back at once, and a text without them comes back unranked while
the ranking runs on the event loop and is saved. The response says
`ranking`, and the word panel asks again until the key words are there.
Waiting cost the first open of every video 2-5 s (2026-11-04: 1.8-2.4 s on
Koyeb for a first open, 0.3 s for the next), and nearly every open is a first.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable

import httpx

from ai_gateway import JEV_URL, async_http_client
from languages import LANGUAGES

log = logging.getLogger(__name__)

URL = JEV_URL
MODEL = "typesafe/jev-1.13"   # pinned, like video_quality.py
RUBRIC_VERSION = 1            # bump when a prompt changes; saved ranks are redone

# One request answers its questions largely one after another: about 0.5 s plus
# 1.8 ms a question, measured 2026-11-05 (1,480 questions: 2.3 s in one request,
# 1.2 s as four at once, same answers). So a long list goes out as concurrent
# requests, each with at least MIN_WORDS_PER_REQUEST words so a short list
# doesn't pay for the split.
PARALLEL_REQUESTS = 4
MIN_WORDS_PER_REQUEST = 60


def spread(items: list, parts: int = PARALLEL_REQUESTS, minimum: int = MIN_WORDS_PER_REQUEST) -> list[list]:
    """`items` dealt into at most `parts` groups of at least `minimum` each."""
    count = max(1, min(parts, len(items) // minimum))
    return [items[i::count] for i in range(count)]

# The list shows the most important missing words as key words: always
# MIN_KEY_WORDS if there are that many, then more from the mean of here and
# general at KEY_FROM, up to MAX_KEY_WORDS. What is left after a learner's known
# words scores lower than a whole text, so the limit is soft: at 2.5 one user
# gets 14 of an episode's 203 missing words, 7 of a song's 21 and the full 15 of
# an article's 111, and someone who knows nearly everything still gets 5.
MIN_KEY_WORDS = 5
MAX_KEY_WORDS = 15
KEY_FROM = 2.5

# What the text is, in the state.
KINDS = {"video": "YouTube video", "series": "TV episode", "movie": "film",
         "article": "article", "song": "song", "text": "text"}

RUBRIC = {
    "here": ("How relevant this word is to understanding `text`: how often it occurs (`count`), "
             "whether it occurs in the lines that matter, and how much of the text a learner "
             "who does not know it would miss."),
    "general": ("How relevant this word is to someone learning the language, whatever the text: "
                "how often they would hear or need it in everyday conversation, series, news and "
                "songs. Names of people, places and brands, interjections, sounds and niche "
                "jargon score low."),
}
HERE = {"1": "A learner would miss nothing without it", "2": "They would miss a detail",
        "3": "They would miss part of a scene or passage",
        "4": "They would miss much of the text", "5": "They could not follow the text without it"}
GENERAL = {"1": "Rare, a name, or niche", "2": "Uncommon", "3": "Common in some topics",
           "4": "Common", "5": "Core everyday vocabulary"}


# Rankings running in the background, by "video:<id>" or "media:<user>:<id>",
# so polls and double clicks don't start a second request for the same text.
# Only touched from the event loop.
_running: dict[str, asyncio.Task] = {}


def ranking(key: str) -> bool:
    """Whether a background ranking for this text is still running."""
    return key in _running


def _in_background(key: str, work: Callable[[], Awaitable[object]]) -> None:
    if key in _running:
        return

    async def run() -> None:
        try:
            await work()
        except Exception:
            log.exception("Could not rank the words of %s", key)

    task = asyncio.get_running_loop().create_task(run())
    _running[key] = task
    task.add_done_callback(lambda _: _running.pop(key, None))


class TooLong(Exception):
    """Jev refused the request as over its token limit."""


class Word:
    """One root of the text: how it is spelled there and how often it occurs."""

    def __init__(self, root: str):
        self.root = root
        self.forms: Counter[str] = Counter()

    def describe(self) -> dict:
        return {"word": self.root, "forms": [form for form, _ in self.forms.most_common(3)],
                "count": sum(self.forms.values())}


def questions(word_ids: list[int]) -> dict:
    out = {}
    for word_id in word_ids:
        out[f"h{word_id}"] = {"type": "choice", "criteria": HERE,
                              "instructions": f"Apply rubric.here to words.w{word_id}."}
        out[f"g{word_id}"] = {"type": "choice", "criteria": GENERAL,
                              "instructions": f"Apply rubric.general to words.w{word_id}."}
    return out


def _expected(probabilities: dict[str, float]) -> float:
    return round(sum(int(k) * v for k, v in probabilities.items()), 2)


async def ask(client: httpx.AsyncClient, state: dict, asked: dict) -> dict[str, list[float]]:
    """[here, general] for each word asked about. Raises if Jev did not answer."""
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = await client.post(URL, json={"model": MODEL, "state": state, "questions": asked})
            if r.status_code == 200 and "answers" in (body := r.json()):
                a = body["answers"]
                ids = {key[1:] for key in asked}
                return {i: [_expected(a[f"h{i}"]["probabilities"]),
                            _expected(a[f"g{i}"]["probabilities"])] for i in ids}
            if r.status_code == 400 and "max_tokens_exceeded" in r.text:
                raise TooLong
            last = RuntimeError(f"Jev HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code < 500 and r.status_code not in (408, 429):
                break
        except (httpx.HTTPError, KeyError) as e:
            last = e
        await asyncio.sleep(attempt)
    raise last or RuntimeError("Jev did not answer")


async def _ask_all(client: httpx.AsyncClient, state: dict, words: dict[int, Word],
                   split: bool = True) -> dict[str, list[float]]:
    """All the words, in a few concurrent requests when there are many, or in
    two halves if a request is too long."""
    if split and len(groups := spread(list(words.items()))) > 1:
        parts = await asyncio.gather(*(_ask_all(client, state, dict(group), split=False) for group in groups))
        return {k: v for part in parts for k, v in part.items()}
    described = {f"w{word_id}": word.describe() for word_id, word in words.items()}
    try:
        return await ask(client, {**state, "words": described}, questions(list(words)))
    except TooLong:
        if len(words) == 1:
            raise
    items = list(words.items())
    half = len(items) // 2
    left, right = await asyncio.gather(_ask_all(client, state, dict(items[:half]), split=False),
                                       _ask_all(client, state, dict(items[half:]), split=False))
    return {**left, **right}


def words_of(tokens: list[tuple[str, int]], roots: dict[int, str]) -> dict[int, Word]:
    """The text's words by root id, for the ids `roots` names."""
    out: dict[int, Word] = {}
    for form, word_id in tokens:
        if word_id in roots:
            out.setdefault(word_id, Word(roots[word_id])).forms[form.lower()] += 1
    return out


def roots_of(sb, language: str, ids: list[int]) -> dict[int, str]:
    """Root names of the ids, leaving out words audited invalid."""
    out = {}
    for start in range(0, len(ids), 200):
        rows = (sb.table("words").select("id,root,status").eq("language", language)
                .in_("id", ids[start:start + 200]).execute().data)
        out.update({r["id"]: r["root"] for r in rows if r.get("status") != "invalid"})
    return out


async def rank(sb, language: str, kind: str, title: str, text: str,
               tokens: list[tuple[str, int]]) -> dict[str, list[float]]:
    """[here, general] for every word of the text, keyed by word id as a string."""
    ids = list(dict.fromkeys(word_id for _, word_id in tokens))
    words = words_of(tokens, await asyncio.to_thread(roots_of, sb, language, ids))
    if not words:
        return {}
    state = {"title": title, "kind": KINDS.get(kind, "text"), "language": LANGUAGES[language],
             "text": text, "rubric": RUBRIC}
    async with async_http_client("words.importance", timeout=60) as client:
        return await _ask_all(client, state, words)


def importance(scores: list[float]) -> float:
    here, general = scores
    return round((here + general) / 2, 2)


def with_importance(missing: list[dict], ranks: dict[str, list[float]] | None) -> list[dict]:
    """The missing words with their `importance` (None when unranked) and `key`.
    Flagged and invalid words are never key words: the list keeps them apart."""
    ranks = ranks or {}
    out = [{**w, "importance": importance(ranks[str(w["id"])]) if str(w["id"]) in ranks else None,
            "key": False} for w in missing]
    ranked = sorted((w for w in out if w["importance"] is not None
                     and w.get("status") not in ("flagged", "invalid")),
                    key=lambda w: -w["importance"])
    for place, w in enumerate(ranked[:MAX_KEY_WORDS]):
        w["key"] = place < MIN_KEY_WORDS or w["importance"] >= KEY_FROM
    return out


def tokens_of_chunks(chunks: list[dict]) -> list[tuple[str, int]]:
    """(form, word id) for every marked word of a Library item's chunks."""
    return [(chunk["text"][start:end], word_id)
            for chunk in chunks for start, end, word_id in chunk.get("words") or []]


def tokens_of_content(content: list[dict]) -> list[tuple[str, int]]:
    """(form, word id) for every word of a corpus video's parsed content."""
    return [(t["content"], t["id"]) for t in content if t.get("id") is not None]


def video_key(video_id: str) -> str:
    return f"video:{video_id}"


def media_key(user_id: str, media_id: str) -> str:
    return f"media:{user_id}:{media_id}"


async def video_ranks(sb, video_id: str, language: str, content: list[dict],
                      wait: bool = True) -> dict | None:
    """A corpus video's saved ranks, ranking it first if it has none. Without
    `wait`, a video with none comes back None at once and is ranked in the
    background (video_key says whether that is still running)."""
    async def rank_and_save() -> dict:
        text = "".join(t.get("content", "") for t in content)
        ranks = await rank(sb, language, "video", "", text, tokens_of_content(content))
        await asyncio.to_thread(lambda: sb.table("video_word_ranks").upsert({
            "video_id": video_id, "language": language,
            "rubric_version": RUBRIC_VERSION, "ranks": ranks}, on_conflict="video_id").execute())
        return ranks

    try:
        rows = await asyncio.to_thread(lambda: (
            sb.table("video_word_ranks").select("rubric_version,ranks")
            .eq("video_id", video_id).limit(1).execute().data))
        if rows and rows[0]["rubric_version"] == RUBRIC_VERSION:
            return rows[0]["ranks"]
        if not wait:
            _in_background(video_key(video_id), rank_and_save)
            return None
        return await rank_and_save()
    except Exception:
        log.exception("Could not rank the words of video %s", video_id)
        return None


async def media_ranks(sb, store, user_id: str, media_id: str, language: str,
                      tokenize: Callable[[str, str], list[dict]],
                      wait: bool = True) -> dict | None:
    """A Library item's saved ranks, ranking it first if it has none. Items
    imported before chunks carried `words` are read with `tokenize`, as
    media_import.get_media does. Without `wait`, as video_ranks."""
    async def rank_and_save(row: dict) -> dict:
        chunks = row.get("chunks") or []
        text = "\n".join(chunk["text"] for chunk in chunks)
        tokens = (tokens_of_chunks(chunks) if all("words" in chunk for chunk in chunks)
                  else tokens_of_content(tokenize(text, language)))
        ranks = await rank(sb, language, row["kind"], row["title"], text, tokens)
        await asyncio.to_thread(store.save_word_ranks, user_id, language, media_id,
                                ranks, RUBRIC_VERSION)
        return ranks

    try:
        row = await asyncio.to_thread(store.get, user_id, language, media_id,
                                      "kind,title,chunks,word_ranks,word_ranks_version")
        if row is None:
            return None
        if row.get("word_ranks") is not None and row.get("word_ranks_version") == RUBRIC_VERSION:
            return row["word_ranks"]
        if not wait:
            _in_background(media_key(user_id, media_id), lambda: rank_and_save(row))
            return None
        return await rank_and_save(row)
    except Exception:
        log.exception("Could not rank the words of media %s", media_id)
        return None
