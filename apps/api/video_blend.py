"""The recommendation order: what a learner understands, then what's worth watching.

Known-word share alone puts sermons, kids' videos and scripted drama on top,
because simple talk is easy to follow. So the top 20% by known words is
reordered by a weighted geometric mean of percentiles within that 20%, the same
way ytpipeline.blend() combines scores for the queue. Weights and thresholds
were picked by eye from a comparison of top 50s on 2026-11-02.

Engagement isn't an input yet: most of the corpus has no view count here.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable
from typing import Any

POOL_SHARE = 0.2
WEIGHTS = {"known": 0.30, "interest": 0.25, "easy_grammar": 0.25, "text": 0.10, "clean": 0.10}
# Below this a percentile counts as this, so one bad score can't zero a video.
MIN_PERCENTILE = 0.02
# A signal a video doesn't have counts as the middle of the pool.
UNKNOWN_PERCENTILE = 0.5
TRASH_FROM = 7
DULL_TO = 2
PER_CHANNEL = 2


def rejected(look: dict[str, Any] | None) -> str | None:
    """Why a judged video is never recommended, or None to keep it."""
    if not look:
        return None
    if look["sensitive"] == "strong":
        return "sensitive"
    if look["trash"] >= TRASH_FROM:
        return "trash"
    if look["interest"] <= DULL_TO:
        return "dull"
    return None


def percentiles(values: list[float | None]) -> list[float]:
    """Each value's mid-rank share among the values that exist."""
    known = sorted(v for v in values if v is not None)
    if not known:
        return [UNKNOWN_PERCENTILE] * len(values)
    return [UNKNOWN_PERCENTILE if v is None
            else (bisect.bisect_left(known, v) + bisect.bisect_right(known, v)) / 2 / len(known)
            for v in values]


def _blended(pool: list[tuple[str, float]], signals: dict[str, dict[str, Any]]) -> list[str]:
    """The pool's ids, best first. Scores are ranked within the whole pool,
    before rejections, so filtering doesn't reshuffle what's left."""
    def look_of(vid: str) -> dict[str, Any]:
        return signals.get(vid, {}).get("look") or {}

    columns = {
        "known": [ratio for _, ratio in pool],
        "interest": [look_of(vid).get("interest") for vid, _ in pool],
        "clean": [None if "trash" not in look_of(vid) else -look_of(vid)["trash"] for vid, _ in pool],
        "text": [signals.get(vid, {}).get("text") for vid, _ in pool],
        "easy_grammar": [None if signals.get(vid, {}).get("grammar") is None else -signals[vid]["grammar"]
                         for vid, _ in pool],
    }
    scores = [1.0] * len(pool)
    for name, weight in WEIGHTS.items():
        for i, p in enumerate(percentiles(columns[name])):
            scores[i] *= max(p, MIN_PERCENTILE) ** weight
    # Stable: ties keep known-words order.
    order = sorted(range(len(pool)), key=lambda i: -scores[i])
    return [pool[i][0] for i in order]


def rank(candidates: list[tuple[str, float]], signals: dict[str, dict[str, Any]],
         in_list: Callable[[str], bool] | None = None) -> list[str]:
    """Ids in recommendation order. `candidates` is every video the learner
    could be shown, as (id, share of words known), most understood first.
    `in_list` narrows to a category after the pool is taken, so a video's score
    doesn't depend on which list it's in.

    The rest of a small category follows its pool in known-words order. Videos
    over the channel limit go last rather than vanish, so a thin list doesn't
    shrink to a few channels' two videos each."""
    size = max(1, int(len(candidates) * POOL_SHARE))
    ordered = _blended(candidates[:size], signals) + [vid for vid, _ in candidates[size:]]
    out, over_limit, per_channel = [], [], {}
    for vid in ordered:
        look = signals.get(vid, {}).get("look")
        if rejected(look) or (in_list and not in_list(vid)):
            continue
        channel = look.get("channel") if look else None
        if channel:
            per_channel[channel] = per_channel.get(channel, 0) + 1
            if per_channel[channel] > PER_CHANNEL:
                over_limit.append(vid)
                continue
        out.append(vid)
    return out + over_limit


def _paged(query: Callable[[], Any]) -> list[dict[str, Any]]:
    out, page = [], 0
    while True:
        rows = query().range(page * 1000, page * 1000 + 999).execute().data
        out += rows
        if len(rows) < 1000:
            return out
        page += 1


def load_signals(sb) -> dict[str, dict[str, dict[str, Any]]]:
    """{language: {video id: signals}} for languages that have judged videos.
    A language with none is left out and keeps its known-words order."""
    looks = _paged(lambda: sb.table("video_looks").select(
        "video_id,language,channel,interest,trash,sensitive").order("video_id"))
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for row in looks:
        out.setdefault(row["language"], {})[row["video_id"]] = {"look": row}
    for language, videos in out.items():
        scores = _paged(lambda lang=language: sb.table("video_scores").select(
            "video_id,grammar,content,developed,transferable").eq("language", lang).order("video_id"))
        for row in scores:
            videos.setdefault(row["video_id"], {}).update(
                grammar=row["grammar"],
                text=(row["content"] + row["developed"] + row["transferable"]) / 3)
    return out
