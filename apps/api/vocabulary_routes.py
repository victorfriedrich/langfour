"""The Vocabulary page's "Common words you never reviewed": learning words
among the corpus's most common that the user never reviewed (most were
imported long ago), and the move of the ones they tick to known.

"Common" is the recommender's ranking of words by the number of videos they
appear in, the same list it suggests words to learn from.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

import vocabulary
from auth import get_current_user
from vocabulary import (
    STUCK_TOP,
    Language,
    MoveRequest,
    StuckWords,
    VocabularyStore,
    WordsMoved,
    get_vocabulary_store,
)

router = APIRouter()


def _common_words(recommender, language: str) -> list[int]:
    try:
        ranked = recommender.recommend_words_to_learn(language, [], n_words=STUCK_TOP)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Language not supported") from exc
    return [r["word_id"] for r in ranked]


@router.get("/api/vocabulary/stuck", response_model=StuckWords)
async def stuck_words(
    request: Request,
    language: Language,
    current_user: dict = Depends(get_current_user),
    store: VocabularyStore = Depends(get_vocabulary_store),
):
    common = await asyncio.to_thread(_common_words, request.app.state.recommender, language)
    return await asyncio.to_thread(vocabulary.stuck_words, store, str(current_user.id), common)


@router.post("/api/vocabulary/status", response_model=WordsMoved)
async def move_words(
    req: MoveRequest,
    current_user: dict = Depends(get_current_user),
    store: VocabularyStore = Depends(get_vocabulary_store),
):
    return await asyncio.to_thread(vocabulary.move_words, store, str(current_user.id),
                                   req.word_ids, req.status)
