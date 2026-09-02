#!/usr/bin/env python3
"""Smoke-test DeepInfra's transcription endpoint with a real network call.

    python3 scripts/check_transcribe.py

check_llm.py deliberately stops at building the client -- it says so -- because
a genuine test needs an audio file. This script synthesises a one-second WAV
with the standard library and posts it, so it exercises DNS, TLS, the API key
and the model slug, not just the constructor.

A 200 is the pass condition. Whisper may return an empty string or a
hallucinated word for a pure tone; the transcript text is not the point.
"""
import math
import os
import struct
import sys
import tempfile
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _tone_wav(path: str, seconds: float = 1.0, rate: int = 16000, hz: float = 440.0) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for i in range(int(rate * seconds)):
            sample = int(12000 * math.sin(2 * math.pi * hz * i / rate))
            w.writeframes(struct.pack("<h", sample))


def main() -> int:
    try:
        from llm_client import transcription_client, DEEPINFRA_BASE_URL
        from models import MODEL_TRANSCRIBE
    except RuntimeError as exc:
        print(f"FAIL  {exc}")
        return 1

    try:
        client = transcription_client()
    except RuntimeError as exc:
        print(f"FAIL  {exc}")
        return 1
    print(f"OK    client built -> {DEEPINFRA_BASE_URL} (model {MODEL_TRANSCRIBE})")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
    try:
        _tone_wav(path)
        print(f"OK    generated {os.path.getsize(path)} byte probe wav")
        with open(path, "rb") as fh:
            result = client.audio.transcriptions.create(
                model=MODEL_TRANSCRIBE,
                file=fh,
            )
        text = getattr(result, "text", "")
        print(f"OK    DeepInfra answered 200 -> transcript {text!r}")
        print("      (empty or nonsense text is expected for a pure tone)")
    except Exception as exc:
        print(f"FAIL  transcription call: {type(exc).__name__}: {exc}")
        return 1
    finally:
        os.unlink(path)

    print("\nDeepInfra reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
