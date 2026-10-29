"""Pronunciation audio for the extension's word popups, from ElevenLabs.

The key bills per character, so it stays here: the extension asks this
endpoint, which only speaks short texts for signed-in users and remembers
what it already paid for. The extension's messages carry text, not bytes,
so the audio comes back base64-encoded in JSON.
"""

from __future__ import annotations

import base64
import os
from collections import OrderedDict

import requests
from fastapi import APIRouter, Body, Depends, HTTPException

from auth import get_current_user
from languages import require_code

router = APIRouter()

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Flash v2.5 is multilingual and costs half a credit per character. The voice
# is one of ElevenLabs' default voices, which every plan may use over the API.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_MODEL_ID = "eleven_flash_v2_5"

# A word or a short phrase; anything longer is not what the popup asks for.
MAX_CHARS = 100
CACHE_SIZE = 2000

_cache: OrderedDict[tuple[str, str], str] = OrderedDict()


def _synthesize(text: str, language: str) -> bytes:
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Speech is not configured")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_VOICE_ID
    response = requests.post(
        ELEVENLABS_URL.format(voice_id=voice_id),
        params={"output_format": "mp3_44100_64"},
        headers={"xi-api-key": api_key, "Accept": "audio/mpeg"},
        json={
            "text": text,
            "model_id": os.getenv("ELEVENLABS_MODEL_ID", "").strip() or DEFAULT_MODEL_ID,
            "language_code": language,
        },
        timeout=15,
    )
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"ElevenLabs answered {response.status_code}")
    return response.content


@router.post("/api/tts")
def speak(
    text: str = Body(...),
    language: str = Body(...),
    current_user: dict = Depends(get_current_user),
):
    text = " ".join(text.split())
    if not text or len(text) > MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"Text must be 1 to {MAX_CHARS} characters")
    try:
        code = require_code(language)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve

    key = (code, text.lower())
    audio = _cache.get(key)
    if audio is None:
        audio = base64.b64encode(_synthesize(text, code)).decode("ascii")
        _cache[key] = audio
        if len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    return {"audio": audio, "content_type": "audio/mpeg"}
