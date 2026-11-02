"""Watched videos and the recap of yesterday's (watch.py): the extension
reports desktop watching and the history page, the web Videos page lists and
unmarks, and Practice and the extension popup show the recap."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

import watch
from auth import get_current_user
from vocabulary import Language
from watch import (
    DesktopWatch,
    HistoryKept,
    HistoryRead,
    Recap,
    RecapAdd,
    RecapAdded,
    RecapClose,
    Unmark,
    VideoId,
    WatchedList,
    WatchStatus,
    WatchStore,
    get_watch_store,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _record_heard(store: WatchStore, user_id: str, language: str, video_ids: list[str]) -> None:
    for video_id in video_ids:
        try:
            watch.record_heard(store, user_id, language, video_id)
        except Exception:
            logger.exception("Could not log the words of %s as heard", video_id)


@router.get("/api/watch", response_model=WatchedList)
async def watched_list(
    language: Language,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    return await asyncio.to_thread(watch.watched_list, store, str(current_user.id), language)


@router.get("/api/watch/recap", response_model=Recap)
async def recap(
    language: Language,
    day: date,
    start: datetime,
    end: datetime,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    if start.tzinfo is None or not (start < end <= start + watch.RECAP_WINDOW):
        raise HTTPException(status_code=422, detail="start and end must bound one day, with a time zone")
    return await asyncio.to_thread(watch.recap, store, str(current_user.id), language, day, start, end)


@router.post("/api/watch/recap/add", response_model=RecapAdded)
async def add_recap_words(
    req: RecapAdd,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    return await asyncio.to_thread(watch.add_recap_words, store, str(current_user.id), req)


@router.post("/api/watch/recap/close", status_code=204)
async def close_recap(
    req: RecapClose,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    await asyncio.to_thread(watch.close_recap, store, str(current_user.id), req)


@router.post("/api/watch/history", response_model=HistoryKept)
async def record_history(
    req: HistoryRead,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    user_id = str(current_user.id)
    kept, heard = await asyncio.to_thread(watch.record_history, store, user_id, req)
    if heard:
        background.add_task(_record_heard, store, user_id, req.language, heard)
    return kept


@router.post("/api/watch/history/off", status_code=204)
async def turn_off_history(
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    await asyncio.to_thread(watch.turn_off_history, store, str(current_user.id))


@router.post("/api/watch/unmark", response_model=WatchStatus)
async def unmark(
    req: Unmark,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    return await asyncio.to_thread(watch.unmark, store, str(current_user.id), req)


@router.get("/api/watch/{video_id}", response_model=WatchStatus)
async def status(
    video_id: VideoId,
    language: Language,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    return await asyncio.to_thread(watch.status, store, str(current_user.id), language, video_id)


@router.post("/api/watch", response_model=WatchStatus)
async def record_desktop(
    req: DesktopWatch,
    background: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    store: WatchStore = Depends(get_watch_store),
):
    user_id = str(current_user.id)
    result = await asyncio.to_thread(watch.record_desktop, store, user_id, req)
    if result.watched:
        background.add_task(_record_heard, store, user_id, req.language, [req.video_id])
    return result
