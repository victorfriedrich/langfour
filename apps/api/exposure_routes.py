"""Words the user read with the extension: reader paragraphs they stayed on
long enough to read, and caption lines shown while a video played. Also the
thumbs on its word popup (practice.rate_word).

The extension decides what counts as read and which of its words are learning
or new (it classifies them locally); this logs them as word_events
'exposure' rows, once per word per page or video (vocabulary.record_seen).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

import practice
import vocabulary
from auth import get_current_user
from practice import PracticeStore, RatingRequest, RatingResult, get_practice_store
from vocabulary import ExposureSummary, SeenRequest, VocabularyStore, get_vocabulary_store

router = APIRouter()


@router.post("/api/exposure", response_model=ExposureSummary)
async def record_seen(
    req: SeenRequest,
    current_user: dict = Depends(get_current_user),
    store: VocabularyStore = Depends(get_vocabulary_store),
):
    return await asyncio.to_thread(vocabulary.record_seen, store, str(current_user.id), req)


@router.post("/api/word-rating", response_model=RatingResult)
async def rate_word(
    req: RatingRequest,
    current_user: dict = Depends(get_current_user),
    store: PracticeStore = Depends(get_practice_store),
):
    return await asyncio.to_thread(practice.rate_word, store, str(current_user.id), req)
