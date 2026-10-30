"""Which words of a paragraph are in the language being learned, in context.

The ChatGPT highlighter marks words from the dictionary one token at a time,
so a Spanish word inside English text ("my friends gave me", "by bus",
"Irregular forms:") gets marked too. With the account's
`userdata.chatgpt_language_check` on, it sends each paragraph here once it
stops changing, with the words it would mark, and keeps only those Jev says
are in the language in that spot.

One Jev request per paragraph, one choice question per word. Measured on a
labelled ChatGPT answer (1,304 words): 0 of 499 Spanish words dropped, 4-5 of
57 Spanish-looking words in English text still marked (mostly an English label
before a colon, "Irregular forms: tuve (tener)"), about 0.3 s per paragraph.
Jev's scores move a little between runs (median 0.01), so a word close to
THRESHOLD can land either way.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from languages import LANGUAGES, require_code
from supabase_client import supabase

router = APIRouter()

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"   # pinned, like word_matching.py
THRESHOLD = 0.5               # p(language) from which a word stays marked
SNIPPET_CHARS = 40            # text shown on each side of the word asked about
PARALLEL = 16

MAX_BLOCKS = 40
MAX_TEXT = 4000
MAX_CONTEXT = 1000
MAX_WORDS = 80


class Block(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    before: str = Field("", max_length=MAX_CONTEXT)
    after: str = Field("", max_length=MAX_CONTEXT)
    # [start, end) offsets into `text` of the words to check
    words: list[tuple[int, int]] = Field(max_length=MAX_WORDS)


class CheckRequest(BaseModel):
    language: str
    blocks: list[Block] = Field(max_length=MAX_BLOCKS)


def enabled_for(user_id: str) -> bool:
    res = (supabase.table("userdata").select("chatgpt_language_check")
           .eq("user_id", user_id).limit(1).execute())
    return bool((res.data or [{}])[0].get("chatgpt_language_check"))


def question(code: str, text: str, start: int, end: int) -> dict:
    name = LANGUAGES[code]
    left = text[max(0, start - SNIPPET_CHARS):start]
    right = text[end:end + SNIPPET_CHARS]
    snippet = f"…{left}[{text[start:end]}]{right}…"
    return {
        "type": "choice",
        "instructions": (f"In `line`: \"{snippet}\". Which language is the word in [brackets] "
                         "written in, as used in this spot? `before` and `after` are the "
                         "neighbouring lines, for context."),
        "criteria": {
            # Keyed by the language code: "es" scored better than "target".
            code: (f"{name}: it belongs to a {name} phrase or sentence, or is a {name} word "
                   f"or form being discussed or listed. A {name} word named inside an "
                   f"English sentence is still {name}."),
            "en": ("English: it belongs to English prose, including English labels and "
                   "headings such as \"Irregular forms:\" or \"Useful phrasing:\"."),
            "other": ("Neither: a placeholder letter like X or Y, a word ending such as -imos, "
                      "an acronym, or a name."),
        },
    }


async def ask_jev(client: httpx.AsyncClient, code: str, block: Block) -> list[float] | None:
    """p(language) for each of the block's words, or None if Jev did not answer."""
    state = {"before": block.before, "line": block.text, "after": block.after}
    questions = {f"q{i}": question(code, block.text, s, e) for i, (s, e) in enumerate(block.words)}
    for _ in range(3):
        try:
            r = await client.post(URL, json={"model": MODEL, "state": state, "questions": questions})
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and "answers" in (body := r.json()):
            answers = body["answers"]
            return [answers[f"q{i}"]["probabilities"].get(code, 0.0) for i in range(len(block.words))]
        if r.status_code < 500 and r.status_code not in (408, 429):
            break
    return None


@router.get("/api/language-check")
async def language_check_setting(current_user=Depends(get_current_user)):
    return {"enabled": await asyncio.to_thread(enabled_for, str(current_user.id))}


@router.post("/api/language-check")
async def language_check(payload: CheckRequest, current_user=Depends(get_current_user)):
    try:
        code = require_code(payload.language)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    for block in payload.blocks:
        if any(not 0 <= s < e <= len(block.text) for s, e in block.words):
            raise HTTPException(status_code=400, detail="Word offsets outside the text")
    if not await asyncio.to_thread(enabled_for, str(current_user.id)):
        raise HTTPException(status_code=403, detail="The language check is off for this account")

    semaphore = asyncio.Semaphore(PARALLEL)

    async def one(client: httpx.AsyncClient, block: Block) -> list[float] | None:
        if not block.words:
            return []
        async with semaphore:
            return await ask_jev(client, code, block)

    async with httpx.AsyncClient(timeout=20, headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}) as client:
        scores = await asyncio.gather(*(one(client, b) for b in payload.blocks))
    # A block Jev did not answer comes back as null: the extension marks its
    # words as before rather than dropping them.
    return {"blocks": [
        None if p is None else {"in_language": [x >= THRESHOLD for x in p], "p": p}
        for p in scores
    ]}
