"""A YouTube channel's Favourite button and Langfour tab (channels.py).

    GET  /api/channels/{channel_id}?language=es     the tab: progress, core words
    GET  /api/channels/{channel_id}/favourite       the button, on every channel page
    POST /api/channels/{channel_id}/favourite       {language, favourite}
    POST /api/channels/{channel_id}/core-words      {language}: add them as learning

The extension calls these from youtube.com through the content script's relay.
"""

from __future__ import annotations

import asyncio
import os
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Request

import channels
from auth import get_current_user
from channels import (
    CHANNEL_ID,
    ChannelStore,
    ChannelView,
    CoreWordsAdded,
    CoreWordsRequest,
    Favourite,
    FavouriteRequest,
    get_channel_store,
)
from vocabulary import Language, VocabularyStore, get_vocabulary_store

router = APIRouter()

ChannelId = Annotated[str, Path(pattern=CHANNEL_ID)]


def _recommender(request: Request, language: str):
    recommender = request.app.state.recommender
    if language not in recommender.languages:
        raise HTTPException(status_code=404, detail="Language not supported")
    return recommender


@router.get("/api/channels/{channel_id}", response_model=ChannelView)
async def channel_view(
    channel_id: ChannelId,
    language: Language,
    request: Request,
    current_user: dict = Depends(get_current_user),
    store: ChannelStore = Depends(get_channel_store),
):
    recommender = _recommender(request, language)
    return await asyncio.to_thread(channels.channel_view, store, recommender,
                                   str(current_user.id), channel_id, language)


@router.get("/api/channels/{channel_id}/favourite", response_model=Favourite)
async def is_favourite(
    channel_id: ChannelId,
    current_user: dict = Depends(get_current_user),
    store: ChannelStore = Depends(get_channel_store),
):
    favourited_at = await asyncio.to_thread(store.favourited_at, str(current_user.id), channel_id)
    return {"favourite": favourited_at is not None}


@router.post("/api/channels/{channel_id}/favourite", response_model=Favourite)
async def favourite(
    channel_id: ChannelId,
    req: FavouriteRequest,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    store: ChannelStore = Depends(get_channel_store),
):
    user_id = str(current_user.id)
    is_new = await asyncio.to_thread(channels.set_favourite, store, user_id, channel_id,
                                     req.language, req.favourite)
    if is_new:
        background.add_task(channels.queue_channel, store, user_id, channel_id, req.language,
                            os.getenv("YOUTUBE_API_KEY"))
    return {"favourite": req.favourite}


@router.post("/api/channels/{channel_id}/core-words", response_model=CoreWordsAdded)
async def add_core_words(
    channel_id: ChannelId,
    req: CoreWordsRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    store: ChannelStore = Depends(get_channel_store),
    vocab: VocabularyStore = Depends(get_vocabulary_store),
):
    recommender = _recommender(request, req.language)
    return await asyncio.to_thread(channels.add_core_words, store, vocab, recommender,
                                   str(current_user.id), channel_id, req.language)
