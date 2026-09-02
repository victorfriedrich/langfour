#!/usr/bin/env python3
"""Smoke-test the LLM providers. Run after changing keys or model ids.

    python3 scripts/check_llm.py

Checks, in order: OpenRouter reachable, both model tiers answer, structured
output works end to end, and DeepInfra's transcription endpoint is reachable.
Exits non-zero on the first hard failure.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import BaseModel  # noqa: E402


class _Probe(BaseModel):
    ok: bool
    language: str


def main() -> int:
    try:
        from llm_client import client, parse_structured, transcription_client
        from models import MODEL_SMART, MODEL_FAST, MODEL_TRANSCRIBE
    except RuntimeError as exc:
        print(f"FAIL  {exc}")
        return 1

    for label, model in (("FAST ", MODEL_FAST), ("SMART", MODEL_SMART)):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                max_tokens=10,
            )
            print(f"OK    {label} {model} -> {r.choices[0].message.content!r}")
        except Exception as exc:
            print(f"FAIL  {label} {model}: {exc}")
            return 1

    try:
        out = parse_structured(
            model=MODEL_SMART,
            messages=[{"role": "user", "content":
                       'Return JSON: ok=true, language="es".'}],
            schema_model=_Probe,
            max_tokens=60,
        )
        print(f"OK    structured output -> {out!r}")
    except Exception as exc:
        print(f"FAIL  structured output: {exc}")
        return 1

    # Transcription needs an audio file to test properly; just prove the client
    # builds and the key is present.
    try:
        transcription_client()
        print(f"OK    DeepInfra client built (model {MODEL_TRANSCRIBE})")
    except RuntimeError as exc:
        print(f"WARN  {exc}")

    print("\nAll good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
