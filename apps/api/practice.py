"""
Practice that happens outside the flashcard systems, on its way to a card.

A ChatGPT practice session (mcp_server.record_practice) reports what the user
recalled. Every answer becomes a word_events row (sql/word_events.sql), the
append-only log of evidence outside the review tables. For a user whose
reviews RemNote schedules, an answer can also become an srs_outbox row
(sql/srs_outbox.sql) naming the card it applies to; the RemNote plugin
learns of them through the inbox, collects them under the sync lease
(remnote_sync.py), adds the review and reports back.

What reaches a card is deliberately conservative, because RemNote can't tell
these reviews from its own (its SDK takes only a score) and uses review
history for research:
  - wrong -> 'again'; right -> 'good', never 'easy';
  - the plugin applies 'good' only to a card that is due (it sees the live card);
  - at most one result per card per day: within one call a wrong answer wins,
    and a later call the same day gets no outbox row for that card.
Answers that don't reach a card stay as events.

Langfour-scheduled users get events only until Langfour cards exist
(docs/plans/learner-word-data-model.md, step 3).
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from supabase_client import supabase

PROVIDER = "remnote"
SOURCE = "chatgpt"

# Recognising the word (target language -> meaning) is the forward card;
# producing it (meaning -> target language) the backward one. Cloze cards
# never take a practice result.
CARD_KIND = {"recognize": "forward", "produce": "backward"}

_IN_CHUNK = 200


def _chunks(items: list, size: int = _IN_CHUNK) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _key(word: str) -> str:
    return word.strip().lower()


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class PracticeAnswer(BaseModel):
    word: str = Field(..., min_length=1, max_length=64,
                      description="The word's dictionary form in the target language, e.g. 'hablar'")
    direction: Literal["recognize", "produce"] = Field(
        ..., description="'recognize': the user saw the word and gave its meaning. "
                         "'produce': the user had to come up with the word themselves.")
    correct: bool


class PracticeRequest(BaseModel):
    language: Literal["es", "de", "it", "fr"]
    answers: list[PracticeAnswer] = Field(..., min_length=1, max_length=200)


class PracticeSummary(BaseModel):
    recorded: int        # answers logged as events
    queued: int          # results on their way to a RemNote card
    not_found: list[str] # words not in the dictionary, so not recorded


class PracticeItem(BaseModel):
    event_id: int
    card_id: str          # RemNote Card _id
    rem_id: str           # RemNote Rem _id of the card's note
    outcome: Literal["again", "good"]
    practiced_at: str


class PracticeDecision(BaseModel):
    event_id: int
    status: Literal["applied", "skipped"]
    reason: str | None = Field(None, max_length=200)
    review_at: int | None = Field(None, description="Unix ms of the review RemNote recorded")

    @model_validator(mode="after")
    def _applied_has_review(self):
        if (self.status == "applied") != (self.review_at is not None):
            raise ValueError("review_at is required when applied, and only then")
        return self


class PracticeReport(BaseModel):
    decisions: list[PracticeDecision] = Field(..., max_length=500)


# ---------------------------------------------------------------------------
# Storage. Like remnote_sync.SyncStore: everything that touches Supabase is
# here, so the logic below runs against an in-memory stand-in in tests.
# ---------------------------------------------------------------------------

class PracticeStore:
    def __init__(self, client):
        self.db = client

    def resolve_words(self, language: str, words: list[str]) -> dict[str, int]:
        """Lowercased word -> word_id: a valid root first, then a valid form."""
        found: dict[str, int] = {}
        for chunk in _chunks(words):
            res = (self.db.table("words").select("id, root")
                   .eq("language", language).eq("status", "valid")
                   .in_("root", chunk).order("id").execute())
            for r in res.data or []:
                found.setdefault(_key(r["root"]), r["id"])
        missing = [w for w in words if w not in found]
        for chunk in _chunks(missing):
            res = (self.db.table("wordforms").select("form, word_id, words!inner(language, status)")
                   .eq("words.language", language).eq("words.status", "valid")
                   .eq("status", "valid").in_("form", chunk).order("word_id").execute())
            for r in res.data or []:
                found.setdefault(_key(r["form"]), r["word_id"])
        return found

    def review_provider(self, user_id: str) -> str:
        res = (self.db.table("userdata").select("review_provider")
               .eq("user_id", user_id).limit(1).execute())
        return (res.data or [{}])[0].get("review_provider") or "langfour"

    def live_cards(self, user_id: str, word_ids: list[int]) -> dict[tuple[int, str], int]:
        """(word_id, kind) -> srs_cards.id for the user's live RemNote notes."""
        cards: dict[tuple[int, str], int] = {}
        for chunk in _chunks(word_ids):
            res = (self.db.table("srs_notes").select("word_id, srs_cards(id, kind)")
                   .eq("user_id", user_id).eq("provider", PROVIDER)
                   .is_("removed_at", "null").in_("word_id", chunk).execute())
            for note in res.data or []:
                for card in note.get("srs_cards") or []:
                    cards.setdefault((note["word_id"], card["kind"]), card["id"])
        return cards

    def cards_practiced_since(self, card_ids: list[int], since: str) -> set[int]:
        """Cards that already have an outbox row from a recall at or after `since`."""
        busy: set[int] = set()
        for chunk in _chunks(card_ids):
            res = (self.db.table("srs_outbox").select("card_id, word_events!inner(occurred_at)")
                   .in_("card_id", chunk).gte("word_events.occurred_at", since).execute())
            busy.update(r["card_id"] for r in res.data or [])
        return busy

    def insert_events(self, rows: list[dict]) -> list[int]:
        """Ids of the new rows, in the order given: Postgres returns the rows
        of a multi-row INSERT in VALUES order."""
        if not rows:
            return []
        res = self.db.table("word_events").insert(rows).execute()
        return [r["id"] for r in res.data or []]

    def insert_outbox(self, rows: list[dict]) -> None:
        if rows:
            self.db.table("srs_outbox").insert(rows).execute()

    def count_pending(self, user_id: str) -> int:
        res = (self.db.table("srs_outbox").select("event_id, word_events!inner(user_id)", count="exact")
               .eq("word_events.user_id", user_id).eq("status", "pending").limit(1).execute())
        return res.count or 0

    def pending(self, user_id: str) -> list[dict]:
        """Pending rows with the RemNote ids the plugin needs. A row whose card
        is gone comes back with srs_cards null."""
        res = (self.db.table("srs_outbox")
               .select("event_id, outcome, word_events!inner(user_id, occurred_at), "
                       "srs_cards(external_id, srs_notes(external_id, removed_at))")
               .eq("word_events.user_id", user_id).eq("status", "pending")
               .order("event_id").limit(500).execute())
        return res.data or []

    def owned_pending(self, user_id: str, event_ids: list[int]) -> set[int]:
        owned: set[int] = set()
        for chunk in _chunks(event_ids):
            res = (self.db.table("srs_outbox").select("event_id, word_events!inner(user_id)")
                   .eq("word_events.user_id", user_id).eq("status", "pending")
                   .in_("event_id", chunk).execute())
            owned.update(r["event_id"] for r in res.data or [])
        return owned

    def decide(self, event_id: int, fields: dict) -> None:
        (self.db.table("srs_outbox").update(fields)
         .eq("event_id", event_id).eq("status", "pending").execute())


def get_practice_store() -> PracticeStore:
    return PracticeStore(supabase)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def record_practice(store: PracticeStore, user_id: str, req: PracticeRequest,
                    now: datetime | None = None) -> PracticeSummary:
    now = now or datetime.now(UTC)
    words = sorted({_key(a.word) for a in req.answers})
    ids = store.resolve_words(req.language, words)
    answers = [(a, ids[_key(a.word)]) for a in req.answers if _key(a.word) in ids]

    event_ids = store.insert_events([
        {"user_id": user_id, "word_id": word_id,
         "kind": "recall_correct" if a.correct else "recall_wrong",
         "source": SOURCE, "occurred_at": now.isoformat(),
         "context": {"direction": a.direction}}
        for a, word_id in answers
    ])

    chosen: dict[int, tuple[int, str]] = {}  # card_id -> (event_id, outcome)
    if answers and store.review_provider(user_id) == PROVIDER:
        cards = store.live_cards(user_id, sorted({w for _, w in answers}))
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        busy = store.cards_practiced_since(sorted(set(cards.values())), day_start.isoformat())
        for (a, word_id), event_id in zip(answers, event_ids, strict=True):
            card_id = cards.get((word_id, CARD_KIND[a.direction]))
            if card_id is None or card_id in busy:
                continue
            outcome = "good" if a.correct else "again"
            previous = chosen.get(card_id)
            if previous is None or (previous[1] == "good" and outcome == "again"):
                chosen[card_id] = (event_id, outcome)
        store.insert_outbox([
            {"event_id": event_id, "card_id": card_id, "outcome": outcome}
            for card_id, (event_id, outcome) in chosen.items()
        ])

    return PracticeSummary(
        recorded=len(event_ids),
        queued=len(chosen),
        not_found=[w for w in words if w not in ids],
    )


def pending_practice(store: PracticeStore, user_id: str,
                     now: datetime | None = None) -> list[PracticeItem]:
    """What the plugin should apply. Rows whose card or Rem is gone are skipped
    here, since the plugin could do nothing with them."""
    now_iso = (now or datetime.now(UTC)).isoformat()
    items: list[PracticeItem] = []
    for row in store.pending(user_id):
        card = row.get("srs_cards")
        note = (card or {}).get("srs_notes") or {}
        if not card or not note or note.get("removed_at"):
            store.decide(row["event_id"], {"status": "skipped", "decided_at": now_iso,
                                           "reason": "card_gone"})
            continue
        items.append(PracticeItem(
            event_id=row["event_id"],
            card_id=card["external_id"],
            rem_id=note["external_id"],
            outcome=row["outcome"],
            practiced_at=row["word_events"]["occurred_at"],
        ))
    return items


def report_practice(store: PracticeStore, user_id: str, report: PracticeReport,
                    now: datetime | None = None) -> int:
    """Record the plugin's decisions; returns how many rows changed. Rows of
    other users, and rows already decided, are ignored."""
    now_iso = (now or datetime.now(UTC)).isoformat()
    owned = store.owned_pending(user_id, sorted({d.event_id for d in report.decisions}))
    decided = 0
    for d in report.decisions:
        if d.event_id not in owned:
            continue
        owned.discard(d.event_id)
        store.decide(d.event_id, {
            "status": d.status,
            "decided_at": now_iso,
            "reason": d.reason,
            "applied_review_at": (datetime.fromtimestamp(d.review_at / 1000, tz=UTC).isoformat()
                                  if d.review_at is not None else None),
        })
        decided += 1
    return decided
