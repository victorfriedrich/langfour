"""Onboarding and daily words (onboarding.py).

    GET /api/onboarding/preview?language=es&level=A1&topics=Cooking&topics=Travel   public
    GET /api/daily-words?language=es&n=15&topics=Cooking                             signed in
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import onboarding
from auth import get_current_user
from onboarding import DailyWords, OnboardingStore, Preview, StartLevel, get_onboarding_store
from vocabulary import Language

router = APIRouter()


def _recommender(request: Request, language: str):
    recommender = request.app.state.recommender
    if language not in recommender.languages:
        raise HTTPException(status_code=404, detail="Language not supported")
    return recommender


def _topics(topics: list[str]) -> list[str]:
    if len(topics) > onboarding.MAX_TOPICS or any(len(t) > 100 for t in topics):
        raise HTTPException(status_code=422, detail="Too many or too long topics")
    return topics


@router.get("/api/onboarding/preview", response_model=Preview)
async def onboarding_preview(
    language: Language,
    request: Request,
    level: StartLevel = "A1",
    topics: list[str] = Query([]),
    store: OnboardingStore = Depends(get_onboarding_store),
):
    recommender = _recommender(request, language)
    return await asyncio.to_thread(onboarding.preview, store, recommender, language, level,
                                   _topics(topics))


@router.get("/api/daily-words", response_model=DailyWords)
async def daily_words(
    language: Language,
    request: Request,
    n: int = Query(15, ge=1, le=onboarding.MAX_DAILY),
    topics: list[str] = Query([]),
    current_user: dict = Depends(get_current_user),
    store: OnboardingStore = Depends(get_onboarding_store),
):
    recommender = _recommender(request, language)
    user_id = str(current_user.id)
    known = set(await recommender.get_known_words(user_id))
    saved = set(await recommender.get_saved_words(user_id))
    return await asyncio.to_thread(onboarding.daily_words, store, recommender, language,
                                   known, saved, _topics(topics), n)
