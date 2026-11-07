"""Judge a video from its thumbnail and title, with a vision model.

Jev reads text only, and clickbait is mostly in the picture: shocked faces, red
arrows, fake drama. So this is a chat completion through OpenRouter, about
$0.0003 per video. scripts/judge_thumbnails.py decides which videos are worth
that; video_blend.py uses the answers.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

from ai_gateway import CHAT_URL, CREDITS_URL, http_client

URL = CHAT_URL
MODEL = os.getenv("VIDEO_LOOKS_MODEL", "google/gemini-2.5-flash")
THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

GENRES = ["entertainment", "story", "review", "gaming", "howto", "explainer", "talk", "news",
          "money", "kids", "religion", "politics", "other"]

PROMPT = """You are curating the home page of a language-learning site for adults learning Spanish. \
Learners pick native Spanish YouTube videos to watch. Judge this video from its thumbnail, title and channel.

Title: {title}
Channel: {channel}

Answer in JSON with these keys:
- "interest": 1-10. Would a curious adult want to click this and enjoy watching it? 10 = genuinely \
intriguing, would watch for fun; 5 = fine, niche; 1 = dull (sermon, lecture recording, ceremony, raw \
gameplay with nothing to follow) or of interest to no adult.
- "trash": 1-10. How cheap or clickbait-y does it look, enough to lower the site's image if featured? \
Look for: exaggerated shocked faces, red arrows and circles, ALL-CAPS outrage, fake relationship or \
family drama ("mi novio me engaña", "hermanastra mala"), scripted moralising skits, sensational or \
misleading promises, low-effort AI art, sexualised framing, get-rich-quick. 1 = tasteful and honest, \
5 = typical YouTube energy, 10 = pure clickbait trash.
- "polish": 1-10. Visual and production quality of the thumbnail itself.
- "sensitive": "none", "mild" or "strong": sexual content, graphic violence, drugs, gore, conspiracy, \
hateful or extreme content.
- "genre": one of {genres}. "story" = narrative or dramatised stories; "talk" = conversation, \
interviews, podcasts; "explainer" = documentary-style or educational explanation; "howto" = practical \
guides, recipes, vlogs about doing things; "entertainment" = comedy, challenges, reactions, vlogs.
""".replace("{genres}", ", ".join(GENRES))


class OutOfCredit(Exception):
    """OpenRouter answered 402. Retrying can't help, and production Jev shares
    the account, so the run has to stop."""


def client() -> httpx.Client:
    return http_client("video.looks", timeout=90)


def credits_left(http: httpx.Client) -> float:
    data = http.get(CREDITS_URL).raise_for_status().json()["data"]
    return data["total_credits"] - data["total_usage"]


def thumbnail(http: httpx.Client, video_id: str) -> bytes | None:
    """None when YouTube has no thumbnail, which means private or deleted."""
    r = http.get(THUMBNAIL_URL.format(video_id=video_id))
    return r.content if r.status_code == 200 else None


def clean(answer: dict[str, Any]) -> dict[str, Any]:
    """The columns for a model answer. The model sometimes puts a topic in
    "sensitive" ("conspiracy", "politics") or skips a key; a missing score
    raises, so the video is judged again on the next run."""
    def score(key: str) -> int:
        return max(1, min(10, round(float(answer[key]))))

    sensitive = str(answer.get("sensitive", "none")).lower()
    if sensitive not in ("none", "mild", "strong"):
        sensitive = "strong" if sensitive == "conspiracy" else "mild"
    genre = answer.get("genre")
    return {"interest": score("interest"), "trash": score("trash"), "polish": score("polish"),
            "sensitive": sensitive, "genre": genre if genre in GENRES else "other"}


def judge(http: httpx.Client, title: str, channel: str | None, image: bytes,
          attempts: int = 3) -> tuple[dict[str, Any], float]:
    """The verdict's columns and what the calls cost, retries included."""
    content = [
        {"type": "text", "text": PROMPT.format(title=title, channel=channel or "?")},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}},
    ]
    cost, last = 0.0, None
    for _ in range(attempts):
        try:
            r = http.post(URL, json={
                "model": MODEL, "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"}, "temperature": 0,
                "reasoning": {"enabled": False}, "usage": {"include": True}})
            if r.status_code == 402:
                raise OutOfCredit(r.text[:200])
            r.raise_for_status()
            body = r.json()
            cost += (body.get("usage") or {}).get("cost") or 0
            text = body["choices"][0]["message"]["content"]
            return clean(json.loads(text[text.find("{"): text.rfind("}") + 1])), cost
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            last = exc
    raise RuntimeError(f"no verdict after {attempts} tries (${cost:.4f}): {last}")
