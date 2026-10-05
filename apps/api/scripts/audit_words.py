#!/usr/bin/env python3
"""Audit dictionary entries with Jev and write each root's and form's status.

    python3 scripts/audit_words.py es                  # every unverified root
    python3 scripts/audit_words.py es --limit 500      # the next 500
    python3 scripts/audit_words.py es --ids 101428 7731 --dry-run

Jev (TypeSafe, on OpenRouter's Decisions API) is a decision model: it answers
typed questions about a state with probabilities, not text. One request per
root carries three kinds of question about the same state (the root and its
forms):

  entry   choice: valid / questionable / invalid, for the entry as a whole
  root    yes/no: is the root a correctly spelled word in dictionary form
  form_N  yes/no per form: does this form belong to this root

A second, small request asks about the root alone: with its forms in view,
Jev rated junk roots that had copied a real verb's Spanish forms (an English
"edit" carrying "editaron", a misspelt "estudar" carrying "estudió") as valid,
root included. On its own the root scores low.

Statuses (sql/word_status.sql):
  valid    p(valid) > VALID_ABOVE and p(root alone) >= ROOT_ALONE_FROM
  invalid  p(invalid) >= INVALID_FROM and p(root) < INVALID_ROOT_BELOW
  flagged  everything else; Claude reviews these and sets valid or invalid
A form scoring below FORM_FLAG_BELOW is flagged on its own, under any root.

--resolve-flagged settles part of the flagged roots with two more questions
about the root alone (is it another language, is it misspelled) on top of the
stored scores. The rules (resolve() below) held at ~95% on two hand-labelled
samples of flagged roots (198 and 99) and settle about 40% of them; the rest
are mostly real words in the wrong form, which need a correction, not a label.
The thresholds come from a hand-labelled sample of 128 roots: Jev never called
junk valid, but it does call real words invalid, so invalid needs both signals.

One root per request, many in flight: packing several roots into one request
was faster but blunted the per-form check (a junk form scored 0.82 instead of
0.25). The raw probabilities are stored in words.audit / wordforms.audit_score,
so the thresholds can be re-tuned without new requests. Only unverified roots
are picked up, so a run can be stopped and resumed.
"""
import argparse
import asyncio
import json
import os
import queue
import sys
import threading
import time

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from languages import require_code

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"      # pinned: the thresholds were measured against it

VALID_ABOVE = 0.7
INVALID_FROM = 0.7
INVALID_ROOT_BELOW = 0.1
FORM_FLAG_BELOW = 0.3
ROOT_ALONE_FROM = 0.4
WRITE_CHUNK = 100     # roots per database write; API requests time out at 8 s
FORMS_PER_READ = 10_000

LANGUAGE_NAMES = {"es": "Spanish", "fr": "French", "it": "Italian", "de": "German"}

# Wording chosen on a hand-labelled sample of 125 roots. Putting these rules in
# the root question too, or naming the storage conventions (article, infinitive)
# in the entry question, pushed ordinary words to "questionable": 100 of 128
# roots flagged instead of 70. No examples: they bias the answer toward them.
NO_FORMS = ("Adverbs, pronouns, conjunctions, prepositions and interjections have no "
            "inflected forms, so an empty form list is normal for them.")
DIMINUTIVES = ("A diminutive or augmentative is not a headword of its own: it belongs "
               "under its base word as a form.")


def questions(language: str, forms: list[str]) -> dict:
    name = LANGUAGE_NAMES[language]
    q = {
        "entry": {
            "type": "choice",
            "instructions": (f"Is this a real {name} word, stored correctly as a dictionary "
                             f"headword? Regional, colloquial, rare and technical words count. "
                             f"{NO_FORMS} {DIMINUTIVES}"),
            "criteria": {
                "valid": f"A real {name} word in dictionary form, and its forms are genuine forms of it.",
                "questionable": (f"A real {name} word, but stored in the wrong dictionary form "
                                 "or with wrong forms, or unclear."),
                "invalid": (f"Not a {name} word: another language, a proper noun or brand, a "
                            "misspelling, an elongated sound, an acronym, or a fragment."),
            },
        },
        "root": {
            "type": "noul",
            "instructions": f"Is the root a correctly spelled {name} word in dictionary form?",
            "criteria": {"true": f"A correctly spelled {name} word in dictionary form.",
                         "false": "Misspelled, another language, a proper noun, or not in dictionary form."},
        },
    }
    for i, form in enumerate(forms):
        q[f"form_{i}"] = {
            "type": "noul",
            "instructions": f'Is "{form}" a form of this root?',
            "criteria": {"true": "An inflection, diminutive or augmentative of this root, correctly spelled.",
                         "false": "A misspelling, a different word, or another language."},
        }
    return q


def resolve_questions(language: str) -> dict:
    name = LANGUAGE_NAMES[language]
    return {
        "foreign": {"type": "noul",
                    "instructions": (f"Is `root` a word of a language other than {name}, such as "
                                     "English, Catalan, Portuguese, Italian or German?"),
                    "criteria": {"true": "Yes, it belongs to another language.",
                                 "false": f"No, it is {name} or not a word at all."}},
        "typo": {"type": "noul",
                 "instructions": (f"Is `root` a misspelling, a fragment, or a run-together of {name} "
                                  "words, rather than a correctly spelled word?"),
                 "criteria": {"true": "Yes, it is misspelled, cut off or run together.",
                              "false": "No, it is spelled correctly."}},
    }


def resolve(audit: dict, foreign: float, typo: float) -> tuple[str, str] | None:
    """A definite status for a flagged root, or None to leave it flagged."""
    p, root = audit["p"], audit["root"]
    if (p["invalid"] >= 0.5 and root < 0.15) or (foreign >= 0.9 and root < 0.2):
        return "invalid", f"jev resolved: invalid {p['invalid']:.2f}, foreign {foreign:.2f}, root {root:.2f}"
    if p["valid"] >= 0.4 and foreign < 0.15 and typo < 0.5 and root >= 0.4:
        return "valid", f"jev resolved: valid {p['valid']:.2f}, foreign {foreign:.2f}, typo {typo:.2f}, root {root:.2f}"
    return None


def root_alone_question(language: str) -> dict:
    name = LANGUAGE_NAMES[language]
    return {"root": {
        "type": "noul",
        "instructions": (f"Is `root` a correctly spelled {name} word in dictionary form? Regional, "
                         "colloquial, rare and technical words count. Nouns are written with "
                         "their article, verbs in the infinitive, other words as they are."),
        "criteria": {"true": f"A correctly spelled {name} word in dictionary form.",
                     "false": "Misspelled, a word of another language, a proper noun, or an inflected form."},
    }}


RETRYABLE = {408, 429, 500, 502, 503, 504, 529}      # 529: TypeSafe overloaded


async def ask(client: httpx.AsyncClient, state: dict, q: dict) -> dict:
    """One decision request, retried on rate limits and transient errors."""
    for attempt in range(5):
        try:
            r = await client.post(URL, json={"model": MODEL, "state": state, "questions": q})
            if r.status_code == 200 and "answers" in (body := r.json()):
                return body
            if r.status_code not in RETRYABLE:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2 ** attempt)
    raise RuntimeError("Jev did not answer after 5 attempts")


def verdict(entry: dict, body: dict, alone: float) -> tuple[dict, list[dict]]:
    """The root's row and its forms' rows for apply_word_audit."""
    a = body["answers"]
    p = a["entry"]["probabilities"]
    root_p = a["root"]["noul"]

    if p["valid"] > VALID_ABOVE and alone >= ROOT_ALONE_FROM:
        status, reason = "valid", f"jev valid {p['valid']:.2f}, root alone {alone:.2f}"
    elif p["invalid"] >= INVALID_FROM and root_p < INVALID_ROOT_BELOW:
        status, reason = "invalid", f"jev invalid {p['invalid']:.2f}, root {root_p:.2f}"
    else:
        status = "flagged"
        reason = (f"jev unsure: valid {p['valid']:.2f}, questionable {p['questionable']:.2f}, "
                  f"invalid {p['invalid']:.2f}, root {root_p:.2f}, root alone {alone:.2f}")

    root_row = {"id": entry["id"], "status": status, "status_reason": reason,
                "audit": {"model": body.get("model"), "choice": a["entry"]["choice"],
                          "p": p, "root": root_p, "root_alone": alone}}
    form_rows = []
    for i, f in enumerate(entry["forms"]):
        score = a[f"form_{i}"]["noul"]
        flagged = score < FORM_FLAG_BELOW
        form_rows.append({"id": f["id"], "status": "flagged" if flagged else "valid", "score": score,
                          "status_reason": f"jev: form of this root {score:.2f}" if flagged else None})
    return root_row, form_rows


# ──────────────────────────────────────────────────────────────── data ──

def load(sb, language: str, ids: list[int] | None, status: str = "unverified") -> list[dict]:
    """Every root to audit, with its forms, read up front: reading page by page
    between batches of requests left Jev idle and timed out under load."""
    if ids:
        words = sb.table("words").select("id, root").in_("id", ids).execute().data
    else:
        words, after = [], 0
        while True:
            page = (sb.table("words").select("id, root").eq("language", language)
                    .eq("status", status).gt("id", after).order("id")
                    .limit(FORMS_PER_READ).execute().data)
            words += page
            if len(page) < FORMS_PER_READ:
                break
            after = page[-1]["id"]

    def forms_of(ids: list[int]) -> list[dict]:
        for attempt in range(3):
            try:
                rows = (sb.table("wordforms").select("id, word_id, form").in_("word_id", ids)
                        .limit(FORMS_PER_READ).execute().data)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        if len(rows) == FORMS_PER_READ and len(ids) > 1:    # may be cut off: split
            half = len(ids) // 2
            return forms_of(ids[:half]) + forms_of(ids[half:])
        return rows

    # One request at a time: the shared client drops connections when several
    # threads use it at once.
    forms: dict[int, list[dict]] = {}
    for i in range(0, len(words), 200):
        for f in forms_of([w["id"] for w in words[i:i + 200]]):
            forms.setdefault(f["word_id"], []).append(f)
    return [{**w, "forms": forms.get(w["id"], [])} for w in words]


class Writer:
    """Every database write on one thread, in order. Writing from several
    threads through one shared client cut connections (timeouts, SSL errors)
    and stretched a 15-minute run to 107 minutes."""

    def __init__(self, sb):
        self.sb, self.queue = sb, queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def put(self, results: list[tuple[dict, list[dict]]]) -> None:
        self.queue.put(results)

    def close(self) -> None:
        self.queue.put(None)
        self.thread.join()

    def _run(self) -> None:
        while (results := self.queue.get()) is not None:
            write(self.sb, results)


def write(sb, results: list[tuple[dict, list[dict]]]) -> None:
    for i in range(0, len(results), WRITE_CHUNK):
        chunk = results[i:i + WRITE_CHUNK]
        payload = {"words_payload": [r for r, _ in chunk],
                   "forms_payload": [f for _, fs in chunk for f in fs]}
        for attempt in range(3):
            try:
                sb.rpc("apply_word_audit", payload).execute()
                break
            except Exception as exc:
                # A failed chunk rolls back: its roots stay unverified and the
                # next run audits them again.
                print(f"  write failed ({attempt + 1}/3): {str(exc)[:120]}", flush=True)
                time.sleep(2 ** attempt)


# ──────────────────────────────────────────────────────────────── run ──

async def audit(entries: list[dict], language: str, parallel: int, on_batch) -> tuple[int, int, float]:
    """Ask Jev about every entry, `parallel` requests in flight, handing results
    to `on_batch` every WRITE_CHUNK roots. Returns (done, failed, cost)."""
    sem = asyncio.Semaphore(parallel)
    pending: list[tuple[dict, dict, list[dict]]] = []
    done = failed = 0
    cost = 0.0
    limits = httpx.Limits(max_connections=parallel, max_keepalive_connections=parallel)
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    async with httpx.AsyncClient(timeout=120, limits=limits, headers=headers) as client:
        async def one(e: dict):
            nonlocal done, failed, cost
            forms = [f["form"] for f in e["forms"]]
            async with sem:
                try:
                    body, alone = await asyncio.gather(
                        ask(client, {"root": e["root"], "forms": forms}, questions(language, forms)),
                        ask(client, {"root": e["root"]}, root_alone_question(language)))
                except Exception as exc:
                    failed += 1
                    print(f"  {e['root']}: {str(exc)[:120]}", flush=True)
                    return
            root_row, form_rows = verdict(e, body, alone["answers"]["root"]["noul"])
            cost += sum((b.get("usage") or {}).get("cost") or 0.0 for b in (body, alone))
            pending.append((e, root_row, form_rows))
            done += 1
            if len(pending) >= WRITE_CHUNK:
                batch = pending[:]
                pending.clear()
                on_batch(batch)

        await asyncio.gather(*(one(e) for e in entries))
        if pending:
            on_batch(pending[:])
    return done, failed, cost


async def resolve_flagged(sb, language: str, parallel: int, dry_run: bool) -> None:
    roots, after = [], 0
    while True:
        page = (sb.table("words").select("id, root, audit").eq("language", language)
                .eq("status", "flagged").not_.is_("audit", "null").gt("id", after)
                .order("id").limit(FORMS_PER_READ).execute().data)
        roots += page
        if len(page) < FORMS_PER_READ:
            break
        after = page[-1]["id"]
    print(f"resolving {len(roots):,} flagged roots", flush=True)

    writer = None if dry_run else Writer(sb)
    sem = asyncio.Semaphore(parallel)
    totals: dict[str, int] = {}
    pending: list[tuple[dict, list]] = []
    limits = httpx.Limits(max_connections=parallel, max_keepalive_connections=parallel)
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    async with httpx.AsyncClient(timeout=120, limits=limits, headers=headers) as client:
        async def one(w: dict):
            async with sem:
                try:
                    body = await ask(client, {"root": w["root"]}, resolve_questions(language))
                except Exception as exc:
                    print(f"  {w['root']}: {str(exc)[:120]}", flush=True)
                    return
            foreign, typo = body["answers"]["foreign"]["noul"], body["answers"]["typo"]["noul"]
            decided = resolve(w["audit"], foreign, typo)
            status = decided[0] if decided else "flagged"
            totals[status] = totals.get(status, 0) + 1
            if decided:
                pending.append(({"id": w["id"], "status": decided[0], "status_reason": decided[1],
                                 "audit": {**w["audit"], "foreign": foreign, "typo": typo}}, []))
            if writer and len(pending) >= WRITE_CHUNK:
                writer.put(pending[:])
                pending.clear()

        await asyncio.gather(*(one(w) for w in roots))
    if writer:
        if pending:
            writer.put(pending)
        writer.close()
    print("resolved: " + "  ".join(f"{k} {v:,}" for k, v in sorted(totals.items())), flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("language")
    p.add_argument("--ids", type=int, nargs="+", help="audit these roots, whatever their status")
    p.add_argument("--limit", type=int, help="stop after this many roots")
    p.add_argument("--status", default="unverified",
                   help="audit roots with this status (default: unverified; e.g. valid to re-check)")
    p.add_argument("--parallel", type=int, default=200, help="requests in flight")
    p.add_argument("--dry-run", action="store_true", help="print verdicts, write nothing")
    p.add_argument("--resolve-flagged", action="store_true",
                   help="settle flagged roots with two more questions (see resolve())")
    p.add_argument("--out", help="also append every verdict to this JSONL file")
    a = p.parse_args()

    from supabase_client import supabase as sb  # verifies service_role
    language = require_code(a.language)
    if a.resolve_flagged:
        asyncio.run(resolve_flagged(sb, language, a.parallel, a.dry_run))
        return
    started = time.time()
    entries = load(sb, language, a.ids, a.status)[:a.limit]
    print(f"auditing {len(entries):,} {LANGUAGE_NAMES[language]} roots "
          f"({sum(len(e['forms']) for e in entries):,} forms), loaded in {time.time() - started:.0f}s",
          flush=True)

    totals: dict[str, int] = {}
    writer = None if a.dry_run else Writer(sb)
    out = open(a.out, "a", encoding="utf-8") if a.out else None  # noqa: SIM115 -- closed below

    def on_batch(batch):
        if writer:
            writer.put([(r, fs) for _, r, fs in batch])
        for e, r, fs in batch:
            totals[r["status"]] = totals.get(r["status"], 0) + 1
            if out:
                out.write(json.dumps({"root": e["root"], **r, "forms": {
                    f["form"]: fr["score"] for f, fr in zip(e["forms"], fs, strict=True)}},
                    ensure_ascii=False) + "\n")
            if a.dry_run:
                bad = [f["form"] for f, fr in zip(e["forms"], fs, strict=True) if fr["status"] == "flagged"]
                print(f"  {e['root'][:28]:28} {r['status']:8} {r['status_reason']}"
                      + (f"  forms flagged: {', '.join(bad)}" if bad else ""))
        n = sum(totals.values())
        if n % 2000 < WRITE_CHUNK or n == len(entries):
            print(f"{n:,}/{len(entries):,}  " + "  ".join(f"{k} {v:,}" for k, v in sorted(totals.items()))
                  + f"  [{time.time() - started:.0f}s]", flush=True)

    done, failed, cost = asyncio.run(audit(entries, language, a.parallel, on_batch))
    if writer:
        print("finishing database writes...", flush=True)
        writer.close()
    if out:
        out.close()
    print(f"done: {done:,} audited, {failed:,} failed (still unverified), "
          f"${cost:.4f}, {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
