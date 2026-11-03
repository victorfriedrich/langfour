"""The web Videos page (home.py).

    GET  /api/home?language=es&topic=All&grammar=B1&length=any&q=   the page
    POST /api/home/hide      {language, video_id, channel}           Not interested
    POST /api/home/unhide    {language, video_id, channel}           Undo
    GET  /api/home/return?video_id=…&since=…                         back from YouTube
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import home
from auth import get_current_user
from home import Hidden, HideRequest, Home, HomeStore, Length, Level, Return, get_home_store
from vocabulary import Language
from watch import VideoId

router = APIRouter()


def _recommender(request: Request, language: str):
    recommender = request.app.state.recommender
    if language not in recommender.languages:
        raise HTTPException(status_code=404, detail="Language not supported")
    return recommender


@router.get("/api/home", response_model=Home)
async def home_page(
    language: Language,
    request: Request,
    topic: str = Query(home.ALL, max_length=100),
    grammar: Level | None = None,
    length: Length = "any",
    q: str = Query("", max_length=100),
    current_user: dict = Depends(get_current_user),
    store: HomeStore = Depends(get_home_store),
):
    recommender = _recommender(request, language)
    return await asyncio.to_thread(home.home, store, recommender, str(current_user.id), language,
                                   topic, grammar, length, q)


@router.post("/api/home/hide", response_model=Hidden)
async def hide(
    req: HideRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    store: HomeStore = Depends(get_home_store),
):
    recommender = _recommender(request, req.language)
    return await asyncio.to_thread(home.set_hidden, store, recommender, str(current_user.id),
                                   req, True)


@router.post("/api/home/unhide", response_model=Hidden)
async def unhide(
    req: HideRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    store: HomeStore = Depends(get_home_store),
):
    recommender = _recommender(request, req.language)
    return await asyncio.to_thread(home.set_hidden, store, recommender, str(current_user.id),
                                   req, False)


@router.get("/api/home/return", response_model=Return)
async def came_back(
    video_id: VideoId,
    since: datetime,
    current_user: dict = Depends(get_current_user),
    store: HomeStore = Depends(get_home_store),
):
    if since.tzinfo is None:
        raise HTTPException(status_code=422, detail="since needs a time zone")
    return await asyncio.to_thread(home.came_back, store, str(current_user.id), video_id, since)
