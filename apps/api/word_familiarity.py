"""Which of a text's new words a learner can probably work out, rated with Jev.

For accounts with userdata.known_languages set, the word list of a video or
Library item has three groups instead of key words and the rest:

  probably  they can work it out from a word they know or a cognate. Added
            half-way to known (sql/word_buckets.sql).
  should    the text's most important other words, chosen as key words are
            (word_importance.py). Added as ordinary learning words.
  skip      everything else. Nothing is saved.

Jev rates only the two links in RUBRIC, and commonness scores nothing: common
words with no link belong in `should`. Tried on one learner's real words
(2026-11-04): with commonness in the rubric, words like mandar and oír scored
near the top and were unknown. With this rubric, of the 36 missing words rated
FAMILIAR_FROM or higher across an episode and an article, the learner didn't
know 4, against most of those rated under 3.5.

A rating depends on the learner, not the text, so it is saved per user and word
and each word is asked about once. Like the ranks, the list doesn't wait for it:
words without a rating come back unrated while Jev rates them in the background
(about 1 s for 300 words with the whole vocabulary in the state), the response
says `ranking`, and the panel asks again.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from languages import LANGUAGES
from supabase_client import supabase
from word_importance import MODEL, URL, TooLong, _in_background, ranking, with_importance

log = logging.getLogger(__name__)

router = APIRouter()

RUBRIC_VERSION = 1   # bump when the rubric changes; saved ratings are redone
FAMILIAR_FROM = 4.0

RUBRIC = (
    "Whether this learner could work out the meaning of `words.<id>` from what they already know, the first "
    "time they see it. Judge only two links: "
    "(a) word family: a close relative of a word in `learner.known_words` or `learner.learning_words`, whose "
    "meaning follows from it; "
    "(b) cognate: the same or nearly the same word in a language in `learner.other_languages`, with the same "
    "meaning (check against `translation`). "
    "How common the word is does not count. A common everyday word with neither link scores 1, however likely "
    "the learner is to have met it. A false friend, whose meaning differs from its look-alike, scores 1."
)
SCALE = {
    "1": "No link, or a false friend",
    "2": "A distant link that would not give the meaning",
    "3": "A partial link: they could work it out with context",
    "4": "A clear link: they would probably get it",
    "5": "Nearly the same word: they would get it at once",
}

_PAGE = 1000
_CHUNK = 200


def _chunks(items: list, size: int = _CHUNK):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _select_all(build) -> list[dict]:
    """Page through a select. `build` must set an order: without one, pages can
    overlap and silently drop rows."""
    rows, start = [], 0
    while True:
        page = build().range(start, start + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        start += _PAGE


def known_languages(sb, user_id: str) -> list[str] | None:
    """The account's cognate languages; None means it keeps the old list."""
    rows = (sb.table("userdata").select("known_languages")
            .eq("user_id", user_id).limit(1).execute().data)
    return (rows or [{}])[0].get("known_languages") or None


def saved_scores(sb, user_id: str, word_ids: list[int]) -> dict[int, float]:
    out: dict[int, float] = {}
    for chunk in _chunks(word_ids):
        rows = (sb.table("user_word_familiarity").select("word_id,score")
                .eq("user_id", user_id).eq("rubric_version", RUBRIC_VERSION)
                .in_("word_id", chunk).execute().data)
        out.update({r["word_id"]: float(r["score"]) for r in rows or []})
    return out


def vocabulary(sb, user_id: str, language: str) -> tuple[list[str], list[str]]:
    """The roots of the learner's known and learning words in this language."""
    known_ids = {r["word_id"] for r in _select_all(lambda: (
        sb.table("user_known_words").select("word_id").eq("user_id", user_id).order("word_id")))}
    rows = _select_all(lambda: (
        sb.table("userwords").select("word_id,status,words!inner(root,language)")
        .eq("user_id", user_id).eq("words.language", language).neq("status", "disabled")
        .order("word_id")))
    known = [r["words"]["root"] for r in rows if r["word_id"] in known_ids]
    learning = [r["words"]["root"] for r in rows
                if r["word_id"] not in known_ids and r["status"] == "learning"]
    return known, learning


def word_entries(sb, word_ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for chunk in _chunks(word_ids):
        rows = (sb.table("words").select("id,root,translation,status")
                .in_("id", chunk).execute().data)
        out.update({r["id"]: {"word": r["root"], "translation": r["translation"]}
                    for r in rows or [] if r.get("status") != "invalid"})
    return out


def _expected(probabilities: dict[str, float]) -> float:
    return round(sum(int(k) * v for k, v in probabilities.items()), 2)


async def ask(client: httpx.AsyncClient, state: dict, word_ids: list[int]) -> dict[int, float]:
    """A score per word. Raises if Jev did not answer."""
    questions = {f"k{i}": {"type": "choice", "criteria": SCALE,
                           "instructions": f"Apply `rubric` to words.w{i}."} for i in word_ids}
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = await client.post(URL, json={"model": MODEL, "state": state, "questions": questions})
            if r.status_code == 200 and "answers" in (body := r.json()):
                return {i: _expected(body["answers"][f"k{i}"]["probabilities"]) for i in word_ids}
            if r.status_code == 400 and "max_tokens_exceeded" in r.text:
                raise TooLong
            last = RuntimeError(f"Jev HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code < 500 and r.status_code not in (408, 429):
                break
        except (httpx.HTTPError, KeyError) as e:
            last = e
        await asyncio.sleep(attempt)
    raise last or RuntimeError("Jev did not answer")


async def _ask_all(client: httpx.AsyncClient, learner: dict, entries: dict[int, dict]) -> dict[int, float]:
    """All the words in one request, or in two halves if that is too long."""
    state = {"learner": learner, "rubric": RUBRIC,
             "words": {f"w{i}": entry for i, entry in entries.items()}}
    try:
        return await ask(client, state, list(entries))
    except TooLong:
        if len(entries) == 1:
            raise
    items = list(entries.items())
    half = len(items) // 2
    left, right = await asyncio.gather(_ask_all(client, learner, dict(items[:half])),
                                       _ask_all(client, learner, dict(items[half:])))
    return {**left, **right}


async def rate(sb, user_id: str, language: str, languages: list[str], word_ids: list[int]) -> dict[int, float]:
    """Rate these words for this learner and save the ratings."""
    entries = await asyncio.to_thread(word_entries, sb, word_ids)
    if not entries:
        return {}
    known, learning = await asyncio.to_thread(vocabulary, sb, user_id, language)
    learner = {"learning": LANGUAGES[language], "other_languages": languages,
               "known_words": known, "learning_words": learning}
    async with httpx.AsyncClient(timeout=60, headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}) as client:
        scores = await _ask_all(client, learner, entries)

    def save() -> None:
        rows = [{"user_id": user_id, "word_id": i, "score": s, "rubric_version": RUBRIC_VERSION}
                for i, s in scores.items()]
        for chunk in _chunks(rows, 500):
            sb.table("user_word_familiarity").upsert(chunk, on_conflict="user_id,word_id").execute()

    await asyncio.to_thread(save)
    return scores


def rating_key(user_id: str, language: str) -> str:
    return f"familiarity:{user_id}:{language}"


def with_buckets(missing: list[dict], ranks: dict | None, scores: dict[int, float]) -> list[dict]:
    """The missing words, each with its `familiarity` and `bucket`. The key words
    are chosen from what `probably` leaves, so the second group is never empty
    just because the text's most important words were easy."""
    def familiar(word: dict) -> bool:
        score = scores.get(word["id"])
        return (score is not None and score >= FAMILIAR_FROM
                and word.get("status") not in ("flagged", "invalid"))

    probably = [{**w, "key": False, "bucket": "probably", "familiarity": scores[w["id"]]}
                for w in with_importance([w for w in missing if familiar(w)], ranks)]
    rest = [{**w, "bucket": "should" if w["key"] else "skip", "familiarity": scores.get(w["id"])}
            for w in with_importance([w for w in missing if not familiar(w)], ranks)]
    return probably + rest


async def panel_words(sb, user_id: str, language: str, missing: list[dict], ranks: dict | None) -> dict:
    """What the missing-words endpoints return. A failure here only costs the
    groups: the words come back as they do for every other account."""
    plain = {"missing_words": with_importance(missing, ranks), "ranking": False, "buckets": False}
    try:
        languages = await asyncio.to_thread(known_languages, sb, user_id)
        if not languages:
            return plain
        word_ids = [w["id"] for w in missing]
        scores = await asyncio.to_thread(saved_scores, sb, user_id, word_ids)
        # Invalid words are never rated (and never listed), so they mustn't keep
        # the panel asking.
        unrated = [w["id"] for w in missing if w["id"] not in scores and w.get("status") != "invalid"]
        key = rating_key(user_id, language)
        if unrated:
            _in_background(key, lambda: rate(sb, user_id, language, languages, unrated))
        return {"missing_words": with_buckets(missing, ranks, scores),
                "ranking": bool(unrated) and ranking(key), "buckets": True}
    except Exception:
        log.exception("Could not read word familiarity for %s", user_id)
        return plain


Bucket = Literal["probably", "should", "skip"]


class BucketMove(BaseModel):
    word_id: int
    was: Bucket
    now: Bucket


class AddBucketWords(BaseModel):
    familiar: list[int] = Field(default_factory=list, max_length=5000)
    priority: list[int] = Field(default_factory=list, max_length=5000)
    source: str = Field(max_length=300)
    moves: list[BucketMove] = Field(default_factory=list, max_length=5000)


def add_words(sb, user_id: str, payload: AddBucketWords) -> int:
    added = sb.rpc("add_bucket_words", {
        "p_user_id": user_id, "p_familiar": payload.familiar,
        "p_priority": payload.priority, "p_source": payload.source}).execute().data
    try:
        events = [{"user_id": user_id, "word_id": m.word_id, "kind": "bucket_move", "source": "web",
                   "context": {"from": m.was, "to": m.now, "text": payload.source}}
                  for m in payload.moves]
        for chunk in _chunks(events, 500):
            sb.table("word_events").insert(chunk).execute()
    except Exception:
        # The words are saved; the log of what changed must not undo that.
        log.exception("Could not log the bucket moves of %s", user_id)
    return added or 0


@router.post("/api/word-buckets")
async def add_bucket_words(payload: AddBucketWords, current_user=Depends(get_current_user)):
    try:
        added = await asyncio.to_thread(add_words, supabase, str(current_user.id), payload)
    except Exception as e:
        log.exception("Could not add bucket words")
        raise HTTPException(status_code=500, detail="Could not add the words") from e
    return {"added": added}
