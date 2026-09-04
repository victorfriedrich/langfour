#!/usr/bin/env python3
"""
ingest.py - turn queued videos into transcripts.

    run        claim pending rows for a language and transcribe them
    seed-done  mark every transcript already on disk as done   (one-off)
    submit     queue one video by hand, or on a user's behalf
    reclaim    return rows stuck in 'processing' to 'pending'
    status     row counts per state

The queue is the `video_queue` table in Supabase (sql/video_queue.sql).
`ytpipeline select` fills it; this drains it. Neither knows about the other's
files, which is the whole point: a video is ingested the same way whether
discovery found it, a person typed it in, or a user submitted it from the app.
The primary key is the dedup, so a submission that overlaps the corpus is free.

Claims are compare-and-set on status, so several workers can share one queue.

    python ingest.py seed-done --lang es --ledger data/yt_es.json
    python ingest.py run --lang es --limit 40
    python ingest.py submit --lang es dQw4w9WgXcQ --source manual
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from languages import require_code
from paths import processed_dir, processed_file

TABLE = "video_queue"
MAX_ATTEMPTS = 3

# What outranks what when the queue drains. This used to be decided by accident:
# submit() left `score` NULL, and Postgres sorts NULLs FIRST under `order by
# score desc`, so user rows jumped the queue without anyone saying they should.
# They should -- so it is said here, in the column that means it.
PRIORITY = {"discovery": 0, "user": 10, "manual": 20}
STATUSES = ("pending", "processing", "done", "failed", "skipped")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def batched(seq: Iterable[Any], n: int = 500) -> Iterable[list]:
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ─────────────────────────────────────────────────────────────── queue ──

def pending(sb, lang: str, limit: int, columns: str = "video_id,channel_id,title,attempts",
            max_attempts: int = MAX_ATTEMPTS) -> list[dict]:
    """The queue's one hot query: what to work on next, in drain order.

    claim() and the dry run both need it. While they each spelled it out, the
    dry run could silently disagree with what run() would actually take -- the
    one thing a dry run exists to show."""
    return (sb.table(TABLE).select(columns)
            .eq("lang", lang).eq("status", "pending").lt("attempts", max_attempts)
            .order("priority", desc=True).order("score", desc=True)
            .limit(limit).execute().data)


def claim(sb, lang: str, limit: int, max_attempts: int = MAX_ATTEMPTS) -> list[dict]:
    """Take up to `limit` pending rows. Each claim is a conditional update on
    status='pending', so a row another worker took first simply comes back
    empty and is skipped rather than processed twice."""
    # Over-fetch: some of these will have been taken by another worker.
    rows = pending(sb, lang, limit * 2, max_attempts=max_attempts)
    claimed = []
    for row in rows:
        won = (sb.table(TABLE)
               .update({"status": "processing", "claimed_at": now(),
                        "attempts": (row.get("attempts") or 0) + 1, "error": None})
               .eq("video_id", row["video_id"]).eq("status", "pending")
               .execute().data)
        if won:
            claimed.append(row)
        if len(claimed) >= limit:
            break
    return claimed


def finish(sb, video_id: str, status: str, error: Optional[str] = None) -> None:
    fields: dict[str, Any] = {"status": status, "error": error}
    if status == "done":
        fields["done_at"] = now()
    sb.table(TABLE).update(fields).eq("video_id", video_id).execute()


def reclaim(sb, lang: str, older_than_minutes: int) -> int:
    """A worker that died mid-video leaves 'processing' behind forever."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)).isoformat()
    rows = (sb.table(TABLE).update({"status": "pending"})
            .eq("lang", lang).eq("status", "processing").lt("claimed_at", cutoff)
            .execute().data)
    return len(rows or [])


def submit(sb, lang: str, video_id: str, source: str,
           priority: Optional[int] = None, submitted_by: Optional[str] = None) -> bool:
    """False when the video was already queued (or done) -- not an error."""
    row = {"video_id": video_id, "lang": lang, "source": source,
           "priority": PRIORITY[source] if priority is None else priority,
           "submitted_by": submitted_by}
    res = sb.table(TABLE).upsert(row, on_conflict="video_id",
                                 ignore_duplicates=True).execute()
    return bool(res.data)


def counts(sb, lang: Optional[str]) -> dict[str, int]:
    """limit(1), not head=True: `head` only exists in postgrest >= 0.17, and
    requirements.txt pins supabase==2.7.4, which resolves to 0.16.x. The exact
    count rides on the Content-Range header either way; limit(1) just means one
    row comes back with it."""
    out = {}
    for status in STATUSES:
        q = sb.table(TABLE).select("video_id", count="exact").eq("status", status)
        if lang:
            q = q.eq("lang", lang)
        out[status] = q.limit(1).execute().count or 0
    return out


# ─────────────────────────────────────────────────────────── transcribe ──

def prepare_cache() -> None:
    """Load the word cache before the first transcript is parsed.

    nlp_processing resolves every token against database.word_cache, which is
    an empty dict until this runs. The deleted videoscraper.py called it before
    its first video and ingest.py did not, which is not a slow path but a
    destructive one: with an empty cache every inflected form misses, falls to
    a per-word `words.root` lookup that never consults `wordforms`, raises, and
    is then "learned" -- inserting a duplicate wordform row and, on a negative
    verdict, flagging a healthy root. Those are the shared production tables.

    It is also the preflight that refuses to run on an empty corpus, which is
    what a non-service_role key looks like once RLS is on.

    Imported here, not at module scope: `database` pulls in supabase_client,
    and the queue-only commands must keep working without it.
    """
    from database import initialize_cache
    initialize_cache()


def transcribe(video_id: str, lang: str) -> tuple[str, Optional[str]]:
    """('done'|'failed', error). videoparsing is imported here because it drags
    in Whisper, spaCy and moviepy; the queue commands should not."""
    import videoparsing
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        videoparsing.main(url, lang)
    except Exception as exc:                     # noqa: BLE001 - recorded, not hidden
        return "failed", f"{type(exc).__name__}: {str(exc)[:400]}"
    if processed_file(lang, video_id).exists():
        return "done", None
    return "failed", "no transcript written"


def run(sb, lang: str, limit: int, dry_run: bool = False) -> dict[str, int]:
    rows = pending(sb, lang, limit) if dry_run else claim(sb, lang, limit)
    tally = {"done": 0, "failed": 0}
    # Once per run, and only when there is something to parse: loading it costs
    # a full pass over words/wordforms, and a dry run parses nothing.
    if rows and not dry_run:
        prepare_cache()
    for n, row in enumerate(rows, 1):
        vid = row["video_id"]
        print(f"[{n}/{len(rows)}] {vid}  {(row.get('title') or '')[:60]}", flush=True)
        if dry_run:
            continue
        # A transcript that already exists (a legacy run, a retry) is done: the
        # file is the ground truth, the row only mirrors it.
        if processed_file(lang, vid).exists():
            status, error = "done", None
        else:
            status, error = transcribe(vid, lang)
        finish(sb, vid, status, error)
        tally[status] += 1
        if error:
            print(f"    failed: {error}", flush=True)
    return tally


# ─────────────────────────────────────────────────────────────── seed ──

UC_IN_LINK = re.compile(r"/channel/(UC[A-Za-z0-9_-]{22})")


def channel_id_of(channel: dict) -> Optional[str]:
    """The legacy ledgers never had a ChannelId -- only a ChannelLink, which is
    a /channel/UC... URL for most rows and a /@handle for the rest. A handle
    cannot be resolved without an API call, so those stay NULL."""
    match = UC_IN_LINK.search(channel.get("ChannelLink") or "")
    return match.group(1) if match else None


def seed_done(sb, lang: str, ledger: Optional[Path]) -> tuple[int, int]:
    """One-off migration off the JSON worklist: every transcript on disk is
    'done'; every 'failedrec' the old scraper recorded is 'failed' at the
    attempt cap so it is never retried. Returns (done, failed) rows written."""
    stamp = now()

    # One key set for every row: PostgREST fills keys missing from a bulk
    # payload with NULL, which turns a mixed batch into a NOT NULL violation.
    def row(video_id: str, **fields: Any) -> dict[str, Any]:
        return {"video_id": video_id, "lang": lang, "source": "legacy", "channel_id": None,
                "title": None, "status": "pending", "attempts": 0, "error": None,
                "done_at": None, **fields}

    done = [row(p.name[:-len("_processed.json")], status="done", done_at=stamp)
            for p in sorted(processed_dir(lang).glob("*_processed.json"))]
    failed = []
    if ledger:
        for channel in json.loads(ledger.read_text("utf-8")):
            for v in channel.get("Videos", []):
                if v.get("processed") == "failedrec" and v.get("id"):
                    failed.append(row(v["id"], status="failed", attempts=MAX_ATTEMPTS,
                                      error="legacy scraper: failedrec",
                                      channel_id=channel_id_of(channel),
                                      title=v.get("title")))
    # done wins over failed when both claim a video: the file exists.
    have = {r["video_id"] for r in done}
    failed = [r for r in failed if r["video_id"] not in have]
    for chunk in batched(done + failed):
        sb.table(TABLE).upsert(chunk, on_conflict="video_id").execute()
    return len(done), len(failed)


# ───────────────────────────────────────────────────────────────── cli ──

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices="run seed-done submit reclaim status".split())
    p.add_argument("video_id", nargs="?", help="submit only")
    p.add_argument("--lang", help="ISO 639-1 or English name")
    p.add_argument("--limit", type=int, default=20, help="run: videos per invocation")
    p.add_argument("--dry-run", action="store_true", help="run: list what would be claimed")
    p.add_argument("--ledger", type=Path, help="seed-done: legacy yt_<lang>.json worklist")
    p.add_argument("--source", default="manual", choices=["manual", "user"])
    p.add_argument("--priority", type=int, default=None,
                   help="submit: override the source's default "
                        f"({', '.join(f'{k}={v}' for k, v in PRIORITY.items())})")
    p.add_argument("--submitted-by", help="submit: auth.users id when acting for a user")
    p.add_argument("--older-than", type=int, default=120,
                   help="reclaim: minutes a row may sit in 'processing'")
    a = p.parse_args()

    from supabase_client import supabase as sb   # verifies service_role at import

    if a.command == "status":
        lang = require_code(a.lang) if a.lang else None
        for status, n in counts(sb, lang).items():
            print(f"{status:11} {n:>8,}")
        return

    if not a.lang:
        sys.exit(f"{a.command} needs --lang")
    lang = require_code(a.lang)

    if a.command == "run":
        tally = run(sb, lang, a.limit, a.dry_run)
        if not a.dry_run:
            print(f"done {tally['done']}, failed {tally['failed']}")
    elif a.command == "seed-done":
        done, failed = seed_done(sb, lang, a.ledger)
        print(f"seeded {done:,} done, {failed:,} failed")
    elif a.command == "submit":
        if not a.video_id:
            sys.exit("submit needs a video id")
        fresh = submit(sb, lang, a.video_id, a.source, a.priority, a.submitted_by)
        print("queued" if fresh else "already queued")
    elif a.command == "reclaim":
        print(f"reclaimed {reclaim(sb, lang, a.older_than)}")


if __name__ == "__main__":
    main()
