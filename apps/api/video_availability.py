"""Find the corpus videos that are gone from YouTube, so nobody is sent to them.

A private or deleted video's thumbnail answers 404 at i.ytimg.com. That is free
(no quota, no LLM) and it is the same signal for every video: on 2026-11-02 all
437 of the corpus's 404s were also refused by YouTube's oEmbed (357 private, 80
not found), and of 400 sampled 200s none had gone.

blacklist.txt removed the 434 that were gone on 2026-10-17, once. This is what
keeps up after that: a daemon thread sweeps every loaded video at boot and once
a day after, so a video that goes dark later is hidden within a day, and one
that comes back is shown again. The first sweep from Koyeb found 7 of 23,495,
all 200s or 404s, so YouTube's block on cloud IPs for captions and audio does
not reach thumbnails. The result only lives in memory: a sweep costs a few
minutes of small requests, and a table would add a write path to save the few
minutes after a deploy before the first sweep ends. Those minutes recommend as
before.

Anything but a 404 or a 200 says nothing about the video, so it keeps the state
it had, and the log line says how many went unanswered.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger(__name__)
# httpx logs each request at INFO: 23,000 lines a sweep, burying everything else.
logging.getLogger("httpx").addFilter(lambda record: "i.ytimg.com" not in record.getMessage())

THUMBNAIL ="https://i.ytimg.com/vi/{}/mqdefault.jpg"
PARALLEL = 8
SWEEP_EVERY_S = 24 * 3600
# 2% of all transcripts ever ingested were gone on 2026-11-02. Far above that the
# answers aren't about the videos, and believing them would empty the
# recommendations.
MAX_GONE_SHARE = 0.2


def is_gone(http: httpx.Client, video_id: str) -> bool | None:
    """Whether YouTube still has the video; None when it didn't say."""
    try:
        return {200: False, 404: True}.get(http.head(THUMBNAIL.format(video_id)).status_code)
    except httpx.HTTPError:
        return None


def sweep(http: httpx.Client, video_ids: Sequence[str], previous: set[str],
          stop: threading.Event) -> set[str]:
    """The videos that are gone now. Unanswered ones keep their previous state;
    `previous` comes back whole if the sweep can't be believed or is stopped."""
    def check(video_id: str) -> bool | None:
        # Without this a shutdown waits for the pool to drain the whole corpus.
        return None if stop.is_set() else is_gone(http, video_id)

    with ThreadPoolExecutor(PARALLEL) as pool:
        answers = list(pool.map(check, video_ids))
    if stop.is_set():
        return previous

    gone = {v for v, answer in zip(video_ids, answers, strict=True)
            if answer or (answer is None and v in previous)}
    unanswered = answers.count(None)
    if len(gone) > MAX_GONE_SHARE * len(video_ids):
        print(f"video sweep: ignored, {len(gone)} of {len(video_ids)} look gone", flush=True)
        return previous
    print(f"video sweep: {len(gone)} of {len(video_ids)} gone, {unanswered} unanswered", flush=True)
    return gone


def run_forever(video_ids: Sequence[str], publish: Callable[[set[str]], None],
                stop: threading.Event) -> None:
    gone: set[str] = set()
    with httpx.Client(timeout=15) as http:
        while not stop.is_set():
            try:
                gone = sweep(http, video_ids, gone, stop)
                publish(gone)
            except Exception:
                log.exception("video sweep failed")
            stop.wait(SWEEP_EVERY_S)


def start(video_ids: Sequence[str], publish: Callable[[set[str]], None]) -> threading.Event:
    """Sweep in the background, handing each result to `publish`; the Event stops it."""
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(video_ids, publish, stop),
                     name="video-sweep", daemon=True).start()
    return stop
