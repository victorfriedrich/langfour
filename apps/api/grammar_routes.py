"""The web app's Grammar tab: the user's grammar book and one lesson at a time.

The same curriculum and progress the MCP grammar tools read (grammar.py), as
structured data. Read only: teaching, practice and recording happen in the
user's chat, over MCP.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

import grammar
from auth import get_current_user
from grammar import GrammarBook, GrammarStore, Lesson, get_grammar_store
from languages import require_code

router = APIRouter()


def _code(language: str) -> str:
    try:
        return require_code(language)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/grammar", response_model=GrammarBook)
async def grammar_book(
    language: str = Query(..., description="Language name or ISO code"),
    current_user: dict = Depends(get_current_user),
    store: GrammarStore = Depends(get_grammar_store),
):
    """Every chapter in teaching order, with the state of each of its concepts."""
    return await asyncio.to_thread(grammar.get_book, store, str(current_user.id), _code(language))


@router.get("/api/grammar/chapters/{chapter_id}", response_model=Lesson)
async def grammar_lesson(
    chapter_id: str,
    language: str = Query(...),
    current_user: dict = Depends(get_current_user),
    store: GrammarStore = Depends(get_grammar_store),
):
    try:
        return await asyncio.to_thread(grammar.get_lesson, store, str(current_user.id),
                                       _code(language), chapter_id)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

