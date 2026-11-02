"""Fit badges on YouTube thumbnails (docs/plans/youtube-plan.md, feature 3).

The extension collects the video ids on a YouTube page as the cards render and
asks, a page at a time, how much of each the user would understand. Videos the
corpus doesn't have get "+ Add", which queues them for the API's own ingest
worker (ingest_worker.py) at the user tier.

The extension sends the learner's language, not the video's, so both routes ask
YouTube what language an unindexed video says it is in. One that says another
comes back "other_language" and isn't queued: an English video on Home would
otherwise be queued as Spanish and spend a proxy download to find out. A video
that says nothing, an unset key or a failed lookup leaves the answer as before;
the transcript's language is still checked after the download.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints

import channels
import ingest
from auth import get_current_user
from supabase_client import supabase
from vocabulary import Language

log = logging.getLogger(__name__)

router = APIRouter()

# One batched call per screenful of cards; the extension sends at most this.
MAX_FIT_IDS = 50
# Videos' stated languages kept in memory: what a video says it is in rarely
# changes, and scrolling back or a second tab shouldn't spend quota again.
LANGUAGE_CACHE = 100_000

YouTubeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{11}$")]


class FitRequest(BaseModel):
    language: Language
    video_ids: list[YouTubeId] = Field(min_length=1, max_length=MAX_FIT_IDS)


class VideoFit(BaseModel):
    status: Literal["scored", "unindexed", "hidden", "other_language"]
    percentUnderstood: float | None = None
    newWords: int | None = None
    language: str | None = None  # other_language: the one YouTube states


class FitResponse(BaseModel):
    videos: dict[str, VideoFit]


class QueueRequest(BaseModel):
    language: Language
    video_id: YouTubeId


class QueueResponse(BaseModel):
    status: Literal["pending", "processing", "done", "failed", "skipped", "other_language"]
    language: str | None = None  # other_language: the one YouTube states


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
    # Asked here rather than on the first "+ Add", so a video in another
    # language never offers it.
    unindexed = [v for v, fit in videos.items() if fit["status"] == "unindexed"]
    if unindexed:
        other = await asyncio.to_thread(_other_languages, unindexed, req.language)
        for video_id, stated in other.items():
            videos[video_id] = {"status": "other_language", "language": stated}
    return {"videos": videos}


@router.post("/api/videos/queue", response_model=QueueResponse, response_model_exclude_none=True)
async def queue_video(
    req: QueueRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.id)
    answer = await asyncio.to_thread(_queue, user_id, req.language, req.video_id)
    if answer is None:
        raise HTTPException(status_code=429, detail="Too many of your videos are waiting")
    return answer


def _queue(user_id: str, language: str, video_id: str) -> dict | None:
    # Before the limit: "not Spanish" is the better answer, and a fit asked
    # before the lookup failed, or 12 hours ago, can still offer "+ Add".
    other = _other_languages([video_id], language)
    if other:
        return {"status": "other_language", "language": other[video_id]}
    # The same limit as a favourite channel's uploads: rows this user has
    # waiting, however they got there.
    if channels.ChannelStore(supabase).waiting_rows(user_id) >= channels.MAX_WAITING:
        return None
    return {"status": ingest.submit_for_user(supabase, language, video_id, user_id)}


_stated: dict[str, str] = {}
_stated_lock = threading.Lock()


def _other_languages(video_ids: list[str], language: str) -> dict[str, str]:
    """The ids YouTube says are in a language other than `language`, with
    that language. A video that states none is left out, and so is every id
    when the key is unset or the lookup fails."""
    with _stated_lock:
        stated = {v: _stated[v] for v in video_ids if v in _stated}
    missing = [v for v in video_ids if v not in stated]
    key = os.getenv("YOUTUBE_API_KEY")
    if missing and key:
        try:
            found = channels.stated_languages(missing, key)
        except Exception:
            log.warning("could not look up the language of %d videos", len(missing), exc_info=True)
        else:
            found = {v: found.get(v, "") for v in missing}
            with _stated_lock:
                if len(_stated) + len(found) > LANGUAGE_CACHE:
                    _stated.clear()
                _stated.update(found)
            stated.update(found)
    return {v: code for v, code in stated.items() if code and code != language}
