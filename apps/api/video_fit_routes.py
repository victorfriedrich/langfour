"""Fit badges on YouTube thumbnails (docs/plans/youtube-plan.md, feature 3).

The extension collects the video ids on a YouTube page as the cards render and
asks, a page at a time, how much of each the user would understand. Videos the
corpus doesn't have get "+ Add", which queues them for the API's own ingest
worker (ingest_worker.py) at the user tier.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints

import channels
import ingest
from auth import get_current_user
from supabase_client import supabase
from vocabulary import Language

router = APIRouter()

# One batched call per screenful of cards; the extension sends at most this.
MAX_FIT_IDS = 50

YouTubeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{11}$")]


class FitRequest(BaseModel):
    language: Language
    video_ids: list[YouTubeId] = Field(min_length=1, max_length=MAX_FIT_IDS)


class VideoFit(BaseModel):
    status: Literal["scored", "unindexed", "hidden"]
    percentUnderstood: float | None = None
    newWords: int | None = None


class FitResponse(BaseModel):
    videos: dict[str, VideoFit]


class QueueRequest(BaseModel):
    language: Language
    video_id: YouTubeId


class QueueResponse(BaseModel):
    status: Literal["pending", "processing", "done", "failed", "skipped"]


def _recommender(request: Request, language: str):
    recommender = request.app.state.recommender
    if language not in recommender.languages:
        raise HTTPException(status_code=404, detail="Language not supported")
    return recommender


def _fit(recommender, user_id: str, video_ids: list[str], language: str):
    known = recommender.known_word_ids(user_id)
    return recommender.fit_videos(video_ids, known, language)


@router.post("/api/videos/fit", response_model=FitResponse, response_model_exclude_none=True)
async def video_fit(
    req: FitRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    recommender = _recommender(request, req.language)
    video_ids = list(dict.fromkeys(req.video_ids))
    videos = await asyncio.to_thread(_fit, recommender, str(current_user.id), video_ids,
                                     req.language)
    return {"videos": videos}


@router.post("/api/videos/queue", response_model=QueueResponse)
async def queue_video(
    req: QueueRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.id)
    status = await asyncio.to_thread(_queue, user_id, req.language, req.video_id)
    if status is None:
        raise HTTPException(status_code=429, detail="Too many of your videos are waiting")
    return {"status": status}


def _queue(user_id: str, language: str, video_id: str) -> str | None:
    # The same limit as a favourite channel's uploads: rows this user has
    # waiting, however they got there.
    if channels.ChannelStore(supabase).waiting_rows(user_id) >= channels.MAX_WAITING:
        return None
    return ingest.submit_for_user(supabase, language, video_id, user_id)
