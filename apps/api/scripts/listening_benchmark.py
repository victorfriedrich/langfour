#!/usr/bin/env python3
"""Listening-difficulty benchmark: how hard each video is to *hear*, as
opposed to how many of its words a learner knows (recommender.py).

    python3 scripts/listening_benchmark.py                    # 30 Spanish videos
    python3 scripts/listening_benchmark.py --n 10 --cooldown 120
    python3 scripts/listening_benchmark.py --cookies cookies.txt
    python3 scripts/listening_benchmark.py --report-only      # recompute from cache

For each video a fixed window (WINDOW_S seconds, starting at WINDOW_START_S)
of audio is downloaded, transcribed twice by Whisper with timestamps, and
measured. Every step is cached in --out, so a run that YouTube interrupts
picks up where it stopped.

YouTube blocks addresses that download quickly, and cloud addresses almost at
once ("Sign in to confirm you're not a bot"). Downloads are therefore one at a
time with a randomised --cooldown between them, and the run stops after
MAX_BLOCKS refusals in a row instead of hammering. From a blocked address,
pass --cookies (a Netscape cookies.txt exported from a logged-in browser) or
run it from a home connection.

Metrics, per video
------------------
Speed
  wpm               words per minute over the whole window, pauses included
  artic_rate        syllables per second of speaking time, pauses removed.
                    The learner-relevant speed: wpm drops when a speaker
                    pauses a lot, artic_rate does not.
  pause_per_min     pauses of PAUSE_S or more per minute
  mean_run_words    words between such pauses. Long unbroken runs are hard to
                    segment into words.
Clarity
  asr_conf          duration-weighted exp(avg_logprob) of Whisper's segments:
                    roughly how sure the recogniser was of what it heard
  asr_disagree      word error rate between two Whisper models on the same
                    audio. Clear speech gets the same transcript from both;
                    mumbling, slurring, overlap and noise do not.
  snr_db            loudness while words are spoken vs. in the gaps between
                    them. Low when music or noise fills the background.
Language
  top1k_cov         share of running words among the 1000 most frequent
  rare_share        share of running words with Zipf frequency < RARE_ZIPF
                    (slang, jargon, names, anglicisms)
  sent_words        mean words per sentence, from Whisper's punctuation

difficulty is the plain mean of the z-scores (signs set so higher = harder).
It is unweighted and illustrative; real weights need learner feedback.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WINDOW_START_S, WINDOW_S = 60, 300   # skip intros; five minutes is enough
MIN_LENGTH_MIN, MAX_LENGTH_MIN = 7, 30
PAUSE_S = 0.4                        # a gap a listener notices
RARE_ZIPF = 3.0                      # rarer than ~1 per million words
MAX_BLOCKS = 3
MIN_LANGUAGE_SHARE = 0.8             # of pieces Whisper hears as the language
LANGUAGE_NAMES = {"es": "spanish", "fr": "french", "de": "german", "it": "italian"}
MODELS = ("openai/whisper-large-v3-turbo", "openai/whisper-large-v3")
RATE = 16000
FRAME_S = 0.02
PIECE_MIN_S, PIECE_MAX_S = 15.0, 28.0   # see videoparsing.py: stay inside one 30 s window

VOWELS = "aeiouáéíóúü"
SYLLABLE = re.compile(rf"[{VOWELS}]+|y(?![{VOWELS}])", re.I)
WORD = re.compile(r"[a-záéíóúüñ]+", re.I)

METRICS = {   # name: +1 if a higher value makes listening harder
    "artic_rate": +1, "wpm": +1, "pause_per_min": -1, "mean_run_words": +1,
    "asr_conf": -1, "asr_disagree": +1, "snr_db": -1,
    "top1k_cov": -1, "rare_share": +1, "sent_words": +1,
}


# ---------------------------------------------------------------- selection

def select_videos(corpus: str, n: int, seed: int) -> list[dict]:
    """The most-viewed eligible video of every channel, shuffled, so each
    video comes from a different speaker. The caller takes them in order
    until n are measured: some turn out not to be in the language."""
    with open(corpus, encoding="utf-8") as fh:
        channels = json.load(fh)
    picks = []
    for ch in channels:
        eligible = [v for v in ch["Videos"]
                    if MIN_LENGTH_MIN <= (v.get("length") or 0) <= MAX_LENGTH_MIN]
        if eligible:
            v = max(eligible, key=lambda v: v.get("Views") or v.get("views") or 0)
            picks.append({"id": v["id"], "title": v["title"], "channel": ch["Name"]})
    random.Random(seed).shuffle(picks)
    return picks


# ----------------------------------------------------------------- download

class Blocked(RuntimeError):
    pass


def download(video_id: str, dest: str, cookies: str | None) -> None:
    """WINDOW_S seconds of audio as 16 kHz mono wav."""
    import yt_dlp
    opts = {
        "format": "bestaudio/best",
        "outtmpl": dest + ".%(ext)s",
        "quiet": True, "no_warnings": True, "noprogress": True,
        "download_ranges": yt_dlp.utils.download_range_func(
            None, [(WINDOW_START_S, WINDOW_START_S + WINDOW_S)]),
        "force_keyframes_at_cuts": False,
        "sleep_interval_requests": 2,
        "js_runtimes": {"node": {}},
        "remote_components": {"ejs:github"},   # YouTube's JS challenge solver
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        "postprocessor_args": {"extractaudio": ["-ac", "1", "-ar", str(RATE)]},
    }
    if cookies:
        opts["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if any(s in msg for s in ("not a bot", "429", "Too Many Requests", "Sign in")):
            raise Blocked(msg) from e
        raise


def load_wav(path: str) -> np.ndarray:
    pcm = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
                          "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


# ------------------------------------------------------------- transcribe

def pieces(samples: np.ndarray) -> list[tuple[float, float]]:
    """Spans of PIECE_MIN_S..PIECE_MAX_S cut at the quietest moment."""
    hop = int(FRAME_S * RATE)
    frames = samples[: len(samples) // hop * hop].reshape(-1, hop)
    energy = np.convolve(np.sqrt((frames ** 2).mean(axis=1)), np.ones(15) / 15, "same")
    duration = len(samples) / RATE
    cuts = [0.0]
    while duration - cuts[-1] > PIECE_MAX_S:
        i, j = int((cuts[-1] + PIECE_MIN_S) / FRAME_S), int((cuts[-1] + PIECE_MAX_S) / FRAME_S)
        cuts.append((i + int(energy[i:j].argmin())) * FRAME_S)
    return list(zip(cuts, [*cuts[1:], duration], strict=True))


def transcribe(wav: str, samples: np.ndarray, model: str, language: str | None) -> dict:
    """Words and segments with timestamps on the window's clock. Without a
    language Whisper detects one per piece; "languages" lists them."""
    from llm_client import transcription_client
    client = transcription_client()

    def one(span):
        start, end = span
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", wav, tmp.name],
                           check=True)
            for attempt in range(4):
                try:
                    with open(tmp.name, "rb") as fh:
                        r = client.audio.transcriptions.create(
                            model=model, file=fh, **({"language": language} if language else {}),
                            response_format="verbose_json",
                            timestamp_granularities=["word", "segment"])
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
        r = r.model_dump() if hasattr(r, "model_dump") else dict(r)
        words = [{"word": w["word"], "start": w["start"] + start, "end": w["end"] + start}
                 for w in r.get("words") or []]
        segs = [{"text": s["text"], "start": s["start"] + start, "end": s["end"] + start,
                 "avg_logprob": s.get("avg_logprob")} for s in r.get("segments") or []]
        return words, segs, r.get("text", ""), r.get("language")

    with ThreadPoolExecutor(max_workers=8) as pool:
        parts = list(pool.map(one, pieces(samples)))
    return {"words": [w for p in parts for w in p[0]],
            "segments": [s for p in parts for s in p[1]],
            "text": " ".join(p[2].strip() for p in parts),
            "languages": [p[3] for p in parts]}


# ---------------------------------------------------------------- measure

def tokens(text: str) -> list[str]:
    return [t.lower() for t in WORD.findall(text)]


def syllables(word: str) -> int:
    return max(1, len(SYLLABLE.findall(word)))


def wer(ref: list[str], hyp: list[str]) -> float:
    if not ref:
        return float("nan")
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def measure(samples: np.ndarray, a: dict, b: dict, language: str) -> dict:
    from wordfreq import top_n_list, zipf_frequency
    duration = len(samples) / RATE
    words = sorted((w for w in a["words"] if tokens(w["word"])), key=lambda w: w["start"])
    if len(words) < 50:
        raise ValueError(f"only {len(words)} words: not enough speech to measure")

    # Speech runs: words joined across gaps shorter than PAUSE_S.
    runs = [[words[0]]]
    for prev, w in pairwise(words):
        (runs[-1].append(w) if w["start"] - prev["end"] < PAUSE_S else runs.append([w]))
    speaking = sum(r[-1]["end"] - r[0]["start"] for r in runs)
    n_syll = sum(syllables(t) for w in words for t in tokens(w["word"]))

    # Loudness inside words vs. in gaps of at least PAUSE_S between them.
    mask = np.zeros(len(samples), bool)
    for w in words:
        mask[int(w["start"] * RATE): int(w["end"] * RATE)] = True
    gap = np.zeros(len(samples), bool)
    for prev, w in pairwise(words):
        if w["start"] - prev["end"] >= PAUSE_S:
            gap[int((prev["end"] + 0.1) * RATE): int((w["start"] - 0.1) * RATE)] = True
    sig, noise = np.mean(samples[mask] ** 2), np.mean(samples[gap] ** 2) if gap.any() else np.nan
    snr = 10 * math.log10(sig / max(noise, 1e-10)) if gap.any() else float("nan")

    segs = [s for s in a["segments"] if s["avg_logprob"] is not None]
    seg_len = np.array([s["end"] - s["start"] for s in segs])
    conf = float(np.sum(np.exp([s["avg_logprob"] for s in segs]) * seg_len) / seg_len.sum()) \
        if segs else float("nan")

    toks = tokens(a["text"])
    top1k = set(top_n_list(language, 1000))
    sentences = [s for s in re.split(r"[.!?¿¡]+", a["text"]) if tokens(s)]
    return {
        "words": len(toks),
        "speech_share": round(speaking / duration, 3),
        "wpm": round(len(words) / duration * 60, 1),
        "artic_rate": round(n_syll / speaking, 2),
        "pause_per_min": round((len(runs) - 1) / duration * 60, 1),
        "mean_run_words": round(len(words) / len(runs), 1),
        "asr_conf": round(conf, 3),
        "asr_disagree": round(wer(toks, tokens(b["text"])), 3),
        "snr_db": round(snr, 1),
        "top1k_cov": round(sum(t in top1k for t in toks) / len(toks), 3),
        "rare_share": round(sum(zipf_frequency(t, language) < RARE_ZIPF for t in toks) / len(toks), 3),
        "sent_words": round(len(toks) / max(1, len(sentences)), 1),
    }


def add_difficulty(rows: list[dict]) -> None:
    for name, sign in METRICS.items():
        vals = np.array([r[name] for r in rows], float)
        mu, sd = np.nanmean(vals), np.nanstd(vals) or 1
        for r, v in zip(rows, vals, strict=True):
            r[f"z_{name}"] = 0.0 if np.isnan(v) else sign * (v - mu) / sd
    for r in rows:
        r["difficulty"] = round(float(np.mean([r[f"z_{m}"] for m in METRICS])), 2)


# ------------------------------------------------------------------- main

def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", default="data/yt_es.json")
    p.add_argument("--language", default="es")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--seed", type=int, default=4)
    p.add_argument("--cooldown", type=float, default=90, help="mean seconds between downloads")
    p.add_argument("--cookies")
    p.add_argument("--out", default="benchmark")
    p.add_argument("--report-only", action="store_true")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    videos = select_videos(args.corpus, args.n, args.seed)
    blocks, downloaded_any = 0, False
    rows = []
    for i, v in enumerate(videos, 1):
        if len(rows) >= args.n:
            break
        base = os.path.join(args.out, v["id"])
        wav, metrics_path = base + ".wav", base + ".metrics.json"
        if os.path.exists(metrics_path):
            with open(metrics_path) as fh:
                rows.append({**v, **json.load(fh)})
            continue
        if args.report_only or os.path.exists(base + ".skip"):
            continue
        if not os.path.exists(wav):
            if downloaded_any:   # cool down before every request but the first
                wait = args.cooldown * random.uniform(0.7, 1.3)
                print(f"  cooling down {wait:.0f}s", flush=True)
                time.sleep(wait)
            downloaded_any = True
            print(f"[{i}/{len(videos)}] downloading {v['id']} ({v['channel']})", flush=True)
            try:
                download(v["id"], base, args.cookies)
                blocks = 0
            except Blocked as e:
                blocks += 1
                print(f"  blocked by YouTube ({blocks}/{MAX_BLOCKS}): {str(e)[:120]}", flush=True)
                if blocks >= MAX_BLOCKS:
                    print("Stopping: YouTube keeps refusing this address. Use --cookies, "
                          "or run from another connection; finished videos are cached.")
                    break
                time.sleep(args.cooldown * 2 ** blocks)
                continue
            except Exception as e:
                print(f"  skipped: {str(e)[:160]}", flush=True)
                continue
        samples = load_wav(wav)
        print(f"[{i}/{len(videos)}] transcribing {v['id']} ({len(samples) / RATE:.0f}s)", flush=True)
        try:
            # The second model detects the language itself, which both checks
            # that the video is in it and keeps it from biasing the comparison.
            b = transcribe(wav, samples, MODELS[1], None)
            ours = {args.language, LANGUAGE_NAMES.get(args.language)}   # code or name, by provider
            share = sum(lang in ours for lang in b["languages"]) / len(b["languages"])
            if share < MIN_LANGUAGE_SHARE:
                print(f"  skipped: {share:.0%} of pieces in {args.language} ({b['languages']})", flush=True)
                with open(base + ".skip", "w") as fh:
                    json.dump(b["languages"], fh)
                continue
            a = transcribe(wav, samples, MODELS[0], args.language)
            with open(base + ".transcripts.json", "w", encoding="utf-8") as fh:
                json.dump({"a": a, "b": b}, fh, ensure_ascii=False)
            m = measure(samples, a, b, args.language)
        except Exception as e:
            print(f"  skipped: {str(e)[:160]}", flush=True)
            continue
        with open(metrics_path, "w") as fh:
            json.dump(m, fh)
        rows.append({**v, **m})
        print("  " + ", ".join(f"{k}={m[k]}" for k in METRICS), flush=True)

    if len(rows) < 2:
        print(f"{len(rows)} videos measured; nothing to compare.")
        return
    add_difficulty(rows)
    rows.sort(key=lambda r: r["difficulty"])
    cols = ["id", "channel", "title", "difficulty", "words", "speech_share", *METRICS]
    with open(os.path.join(args.out, "results.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} videos, easiest first -> {args.out}/results.csv")
    for r in rows:
        print(f"{r['difficulty']:+.2f}  {r['artic_rate']:5.2f} syl/s  conf {r['asr_conf']:.2f}  "
              f"disagree {r['asr_disagree']:.2f}  snr {r['snr_db']:5.1f}  "
              f"rare {r['rare_share']:.2f}  {r['channel'][:24]}")
    names = list(METRICS)
    corr = np.ma.corrcoef(np.ma.masked_invalid(np.array([[r[n] for n in names] for r in rows], float).T))
    print("\nCorrelations (|r| >= 0.5):")
    for x in range(len(names)):
        for y in range(x + 1, len(names)):
            if abs(corr[x, y]) >= 0.5:
                print(f"  {names[x]:>15} ~ {names[y]:<15} r={corr[x, y]:+.2f}")


if __name__ == "__main__":
    main()
