"""Judge thumbnails for the videos most worth it, into video_looks (video_looks.py).

Only the top 20% by known words for the given account and for a fresh account
at --fresh-level get judged, since the recommendation order only reads the top
20% and most learners' top 20% overlap with these. Rerun it after new videos
arrive or a lot of new words are learned: judged videos are skipped. Videos
nobody has judged count as average until then.

OpenRouter credit is shared with production Jev, so a run stops at --cap, on any
402, and won't start below --min-credit. Try --dry-run first.

    python scripts/judge_thumbnails.py --lang es --user-id <uuid> --dry-run
    python scripts/judge_thumbnails.py --lang es --user-id <uuid>

About $0.0003 per video.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import video_blend
import video_looks
from languages import require_code
from paths import PROCESSED_DIR, processed_file
from recommender import MIN_DISTINCT_WORDS, Recommender

COST_PER_VIDEO = 0.0004
PARALLEL = 16


def top_share(rec: Recommender, word_ids: list[int], lang: str) -> list[str]:
    """The video ids in the top 20% by known words, as the recommender takes them."""
    ratios, _, _ = rec._score_documents_by_words(word_ids, lang, distinct=False)
    ids = [f.replace("_processed.json", "") for f in rec.filenames[lang]]
    kept = [i for i in range(len(ids))
            if ids[i] not in rec.hidden_videos and rec.distinct_words_per_doc[lang][i] >= MIN_DISTINCT_WORDS]
    kept.sort(key=lambda i: -ratios[i])
    return [ids[i] for i in kept[: max(1, int(len(kept) * video_blend.POOL_SHARE))]]


def level_words(sb, lang: str, level: str) -> list[int]:
    out, page = [], 0
    while True:
        rows = (sb.table("languagelevels").select("word_id").eq("language", lang)
                .eq("language_level", level).order("id")
                .range(page * 1000, page * 1000 + 999).execute().data)
        out += [r["word_id"] for r in rows]
        if len(rows) < 1000:
            return out
        page += 1


def judged_ids(sb, lang: str) -> set[str]:
    out, page = set(), 0
    while True:
        rows = (sb.table("video_looks").select("video_id").eq("language", lang).order("video_id")
                .range(page * 1000, page * 1000 + 999).execute().data)
        out |= {r["video_id"] for r in rows}
        if len(rows) < 1000:
            return out
        page += 1


def from_corpus(lang: str, video_id: str) -> tuple[str, str | None]:
    processed = json.loads(processed_file(lang, video_id).read_text("utf-8"))
    return processed.get("title") or "", processed.get("creator")


def import_verdicts(sb, lang: str, path: Path, wanted: set[str]) -> None:
    """Store verdicts already paid for, from a JSON-lines file of model answers."""
    judged, rows = judged_ids(sb, lang), []
    for line in path.read_text("utf-8").splitlines():
        answer = json.loads(line)
        vid = answer["id"]
        if "error" in answer or vid not in wanted or vid in judged:
            continue
        rows.append({"video_id": vid, "language": lang, "channel": from_corpus(lang, vid)[1],
                     "model": answer.get("model", video_looks.MODEL), **video_looks.clean(answer)})
        judged.add(vid)
    for start in range(0, len(rows), 500):
        sb.table("video_looks").upsert(rows[start:start + 500], on_conflict="video_id").execute()
    print(f"imported {len(rows):,} verdicts", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lang", default="es")
    p.add_argument("--user-id", required=True, help="the account whose top 20%% to judge")
    p.add_argument("--fresh-level", default="A2", help="word list standing in for a fresh account")
    p.add_argument("--limit", type=int)
    p.add_argument("--cap", type=float, default=1.5, help="stop once this run has cost this many dollars")
    p.add_argument("--min-credit", type=float, default=3.0, help="don't start below this account balance")
    p.add_argument("--dry-run", action="store_true", help="say what a run would cost and stop")
    p.add_argument("--import-verdicts", type=Path, help="store these answers before judging")
    a = p.parse_args()
    lang = require_code(a.lang)

    from supabase_client import supabase as sb  # verifies service_role at import

    rec = Recommender(base_folder=str(PROCESSED_DIR))
    wanted = set(top_share(rec, rec.known_word_ids(a.user_id), lang))
    wanted |= set(top_share(rec, level_words(sb, lang, a.fresh_level), lang))

    if a.import_verdicts and not a.dry_run:
        import_verdicts(sb, lang, a.import_verdicts, wanted)
    todo = sorted(wanted - judged_ids(sb, lang))
    if a.limit:
        todo = todo[:a.limit]

    with video_looks.client() as http:
        left = video_looks.credits_left(http)
        print(f"{len(wanted):,} videos wanted, {len(todo):,} to judge, "
              f"about ${len(todo) * COST_PER_VIDEO:.2f}; ${left:.2f} of credit left", flush=True)
        if a.dry_run or not todo:
            return
        if left < a.min_credit:
            sys.exit(f"credit is below ${a.min_credit:.2f}; not starting")

        lock, stop = threading.Lock(), threading.Event()
        tally = {"judged": 0, "no thumbnail": 0, "failed": 0, "cost": 0.0}

        def one(vid: str) -> None:
            if stop.is_set():
                return
            try:
                image = video_looks.thumbnail(http, vid)
                if image is None:
                    with lock:
                        tally["no thumbnail"] += 1
                    return
                title, channel = from_corpus(lang, vid)
                verdict, cost = video_looks.judge(http, title, channel, image)
                sb.table("video_looks").upsert({
                    "video_id": vid, "language": lang, "channel": channel,
                    "model": video_looks.MODEL, **verdict}, on_conflict="video_id").execute()
                with lock:
                    tally["judged"] += 1
                    tally["cost"] += cost
                    if tally["cost"] >= a.cap:
                        stop.set()
            except video_looks.OutOfCredit:
                stop.set()
                print("OpenRouter answered 402; stopping", flush=True)
            except Exception as exc:
                with lock:
                    tally["failed"] += 1
                print(f"  {vid}: {type(exc).__name__}: {str(exc)[:150]}", flush=True)

        with ThreadPoolExecutor(PARALLEL) as pool:
            list(pool.map(one, todo))
        print(f"{tally['judged']:,} judged, {tally['no thumbnail']:,} without a thumbnail, "
              f"{tally['failed']:,} failed, ${tally['cost']:.4f} spent, "
              f"${video_looks.credits_left(http):.2f} left", flush=True)


if __name__ == "__main__":
    main()
