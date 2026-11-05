"""
ingest_worker.py - drain the video queue from inside the API.

`ingest.py run --mix` on a laptop needed a shell loop to restart it, a
watchdog to stop it, and the laptop awake. Here daemon threads run the same
mix in hour-long chunks for as long as the API is up:

    INGEST_WORKER_MIX=proxy=300     videos per hour per method, per worker; unset = off
    INGEST_WORKER_LANG=es
    INGEST_WORKER_COUNT=2           worker threads; default 2
    INGEST_WORKER_MIN_PRIORITY=1    only rows at or above this priority; default 1

Priority 0 is discovery (ytpipeline's automatic fill), so by default the
worker no longer drains it. Favourite channels (5), user (10) and manual (20)
rows still run. Set 0 to work the whole queue again.

A video is mostly waiting -- on the proxy, YouTube, Jev and Supabase -- so
one worker managed ~200 an hour (14.6 s a video on 2026-11-01) and a second
thread doubles that without a second instance. Claims are compare-and-set
(ingest.claim), so the threads never take the same row.

Only `proxy` belongs in a server's mix: YouTube blocks cloud IPs outright, so
`captions` and `whisper` (both on our own IP) would fail every video. Set
AUDIO_VIA_PROXY=1 too, or the ~8% of videos without usable captions fail on
their audio download.

Each transcript is uploaded to the corpus bucket before its row says done
(corpus_sync.upload_transcript), since this disk is gone at the next deploy.
The recommender sees new videos after a restart, when boot pulls them in.

The worker never stops for good on its own. An Outage (proxy 407, OpenRouter
402, a failed upload) pauses it for OUTAGE_PAUSE_S with the row handed back;
any other error, such as a dropped connection to Supabase, for ERROR_PAUSE_S.
A deploy kills it mid-video, so each chunk starts by reclaiming rows left in
'processing' for over an hour (a laptop worker's slowest Whisper video takes
~15 min, so its rows are not taken from under it).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading

import ingest
from paths import DATA_DIR

log = logging.getLogger(__name__)

CHUNK_HOURS = 1
EMPTY_PAUSE_S = 15 * 60
ERROR_PAUSE_S = 60
OUTAGE_PAUSE_S = 60 * 60
RECLAIM_AFTER_MIN = 60
DEFAULT_COUNT = 2
# Above discovery (0): favourites, user and manual rows only.
DEFAULT_MIN_PRIORITY = 1
# ~190 KB a transcript, 300 an hour: ~1.3 GB a day on a disk that also holds
# the corpus. Pausing beats the API failing to write anything.
MIN_FREE_BYTES = 1 << 30


def configured() -> tuple[str, dict[str, int]] | None:
    """(lang, mix) from the environment, or None when the worker is off."""
    raw = os.getenv("INGEST_WORKER_MIX", "").strip()
    if not raw:
        return None
    from languages import require_code
    return require_code(os.getenv("INGEST_WORKER_LANG", "es")), ingest.parse_mix(raw)


def count() -> int:
    raw = os.getenv("INGEST_WORKER_COUNT", "").strip() or str(DEFAULT_COUNT)
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError(f"INGEST_WORKER_COUNT={raw!r}: use a whole number of workers, 1 or more")
    return int(raw)


def min_priority() -> int:
    raw = os.getenv("INGEST_WORKER_MIN_PRIORITY", "").strip() or str(DEFAULT_MIN_PRIORITY)
    if not raw.isdigit():
        raise ValueError(f"INGEST_WORKER_MIN_PRIORITY={raw!r}: use a whole number, 0 or more")
    return int(raw)


def run_forever(sb, lang: str, mix: dict[str, int], stop: threading.Event,
                publish=None, free_bytes=lambda: shutil.disk_usage(DATA_DIR).free,
                name: str = "ingest worker") -> None:
    if publish is None:
        from corpus_sync import upload_transcript as publish
    while not stop.is_set():
        pause = 0
        try:
            if free_bytes() < MIN_FREE_BYTES:
                log.warning("%s: under 1 GB of disk left, pausing", name)
                pause = OUTAGE_PAUSE_S
            else:
                if n := ingest.reclaim(sb, lang, RECLAIM_AFTER_MIN):
                    print(f"{name}: reclaimed {n} stale rows", flush=True)
                tally = ingest.run_mix(sb, lang, mix, CHUNK_HOURS, sleep=stop.wait,
                                       cache_ready=True, publish=publish, stopped=stop.is_set,
                                       min_priority=min_priority())
                print(f"{name}: {ingest.mix_summary(tally)}", flush=True)
                if not sum(t["done"] + t["failed"] for t in tally.values()):
                    pause = EMPTY_PAUSE_S
        except ingest.Outage as exc:
            log.warning("%s: paused for %d min: %s", name, OUTAGE_PAUSE_S // 60, exc)
            pause = OUTAGE_PAUSE_S
        except Exception:
            log.exception("%s: chunk failed", name)
            pause = ERROR_PAUSE_S
        if pause:
            stop.wait(pause)


def start(sb) -> threading.Event | None:
    """Start the worker threads if INGEST_WORKER_MIX is set; the Event stops them all.

    Call after initialize_cache(): parsing reads the API's word cache, and
    the worker never reloads it (a reload empties it under live requests)."""
    try:
        config = configured()
        workers = count() if config else 0
        min_priority()  # validate now, not on the worker threads
    except ValueError as exc:
        log.error("ingest worker: not started, bad setting: %s", exc)
        return None
    if config is None:
        return None
    lang, mix = config
    if mix.get("proxy") and not os.getenv("CAPTION_PROXY_URL"):
        log.error("ingest worker: not started, the mix has proxy videos but "
                  "CAPTION_PROXY_URL is not set")
        return None
    if mix.keys() - {"proxy"}:
        log.warning("ingest worker: %s run on this server's own IP, which YouTube "
                    "may block", ", ".join(sorted(mix.keys() - {"proxy"})))
    stop = threading.Event()
    for i in range(1, workers + 1):
        threading.Thread(target=run_forever, args=(sb, lang, mix, stop),
                         kwargs={"name": f"ingest worker {i}"},
                         name=f"ingest-worker-{i}", daemon=True).start()
    # print, like ingest.py: the app configures no logging, so info is dropped.
    print(f"ingest worker: started {workers}, each "
          f"{', '.join(f'{k}={v}' for k, v in mix.items())} for {lang}", flush=True)
    return stop
