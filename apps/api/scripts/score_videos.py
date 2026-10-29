"""Score corpus transcripts with Jev into video_scores (video_quality.py).

ingest.py scores each new transcript; this covers the corpus that existed
before that, videos whose scoring failed at ingest, and rescoring after
RUBRIC_VERSION changes. Resumable: videos that already have a row at the
current rubric version are skipped.

    python scripts/score_videos.py --lang es --limit 20     # try a few
    python scripts/score_videos.py --lang es                # the rest
    python scripts/score_videos.py --lang es --report       # hidden counts, no requests

About $0.0002 per video at Jev's prices (~3.6k input tokens, output free).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import video_quality as vq
from languages import require_code
from paths import processed_dir

PARALLEL = 16


def scored_ids(sb, lang: str) -> set[str]:
    out, page = set(), 0
    while True:
        rows = (sb.table("video_scores").select("video_id")
                .eq("language", lang).eq("rubric_version", vq.RUBRIC_VERSION).order("video_id")
                .range(page * 1000, page * 1000 + 999).execute().data)
        out |= {r["video_id"] for r in rows}
        if len(rows) < 1000:
            return out
        page += 1


def report(sb, lang: str) -> None:
    cols = "video_id,p_garbled,p_foreign_lesson,p_sung,content,transferable"
    rows, page = [], 0
    while True:
        chunk = (sb.table("video_scores").select(cols).eq("language", lang).order("video_id")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        rows += chunk
        if len(chunk) < 1000:
            break
        page += 1
    reasons = collections.Counter(vq.hidden(r) or "kept" for r in rows)
    print(f"{len(rows):,} scored")
    for reason, n in reasons.most_common():
        print(f"  {reason:15} {n:>7,}  {n / max(1, len(rows)):6.1%}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lang", required=True)
    p.add_argument("--limit", type=int, help="score at most this many videos")
    p.add_argument("--parallel", type=int, default=PARALLEL)
    p.add_argument("--report", action="store_true", help="only print hidden counts")
    a = p.parse_args()
    lang = require_code(a.lang)

    from supabase_client import supabase as sb  # verifies service_role at import

    if a.report:
        report(sb, lang)
        return
    if lang not in vq.LANGUAGES:
        sys.exit(f"no rubric for {lang}; video_quality.LANGUAGES is {vq.LANGUAGES}")

    done = scored_ids(sb, lang)
    todo = [f for f in sorted(processed_dir(lang).glob("*_processed.json"))
            if f.name[:-len("_processed.json")] not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(done):,} already scored, {len(todo):,} to go", flush=True)

    def one(path: Path) -> str:
        processed = json.loads(path.read_text("utf-8"))
        vid = path.name[:-len("_processed.json")]
        scores = vq.score_and_store(sb, http, vid, lang, processed.get("title") or "",
                                    vq.transcript_words(processed))
        return (vq.hidden(scores) or "kept") if scores else "empty"

    tally: collections.Counter[str] = collections.Counter()
    failed = 0
    with vq.client() as http, ThreadPoolExecutor(a.parallel) as pool:
        futures = {pool.submit(one, f): f for f in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                tally[fut.result()] += 1
            except Exception as exc:
                failed += 1
                print(f"  {futures[fut].name}: {type(exc).__name__}: {str(exc)[:150]}", flush=True)
            if n % 250 == 0 or n == len(todo):
                print(f"[{n:,}/{len(todo):,}] {dict(tally)} failed {failed}", flush=True)


if __name__ == "__main__":
    main()
