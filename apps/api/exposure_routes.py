"""Words the user read with the extension: reader paragraphs they stayed on
long enough to read, and caption lines shown while a video played.

The extension decides what counts as read and which of its words are learning
or new (it classifies them locally); this logs them as word_events
'exposure' rows, once per word per page or video (vocabulary.record_seen).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

import vocabulary
from auth import get_current_user
from vocabulary import ExposureSummary, SeenRequest, VocabularyStore, get_vocabulary_store

router = APIRouter()


@router.post("/api/exposure", response_model=ExposureSummary)
async def record_seen(
    req: SeenRequest,
    current_user: dict = Depends(get_current_user),
    store: VocabularyStore = Depends(get_vocabulary_store),
):
    return await asyncio.to_thread(vocabulary.record_seen, store, str(current_user.id), req)
