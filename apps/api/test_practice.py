import os

# supabase_client builds its client at import time; nothing here touches the network.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from practice import (
    PracticeAnswer,
    PracticeDecision,
    PracticeReport,
    PracticeRequest,
    pending_practice,
    record_practice,
    report_practice,
)

USER, OTHER = "user-1", "user-2"
NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)


class FakeStore:
    """In-memory PracticeStore."""

    def __init__(self, provider="remnote", dictionary=None, cards=None):
        self.provider = provider
        self.dictionary = dictionary or {"hablar": 1, "casa": 2, "comer": 3}
        # (user, word_id, kind) -> card id; card id -> (card external id, rem id)
        self.cards = cards if cards is not None else {
            (USER, 1, "forward"): 10, (USER, 1, "backward"): 11,
            (USER, 2, "forward"): 20, (USER, 2, "cloze"): 21,
        }
        self.card_ids = {10: ("c10", "r1"), 11: ("c11", "r1"), 20: ("c20", "r2"), 21: ("c21", "r2")}
        self.removed_rems: set[str] = set()
        self.events: list[dict] = []
        self.outbox: dict[int, dict] = {}

    def resolve_words(self, language, words):
        return {w: self.dictionary[w] for w in words if w in self.dictionary}

    def review_provider(self, user_id):
        return self.provider

    def live_cards(self, user_id, word_ids):
        return {(w, k): c for (u, w, k), c in self.cards.items() if u == user_id and w in word_ids}

    def cards_practiced_since(self, card_ids, since):
        events = {e["id"]: e for e in self.events}
        return {r["card_id"] for r in self.outbox.values()
                if r["card_id"] in card_ids and events[r["event_id"]]["occurred_at"] >= since}

    def insert_events(self, rows):
        ids = []
        for row in rows:
            ids.append(len(self.events) + 1)
            self.events.append({**row, "id": ids[-1]})
        return ids

    def insert_outbox(self, rows):
        for row in rows:
            self.outbox[row["event_id"]] = {**row, "status": "pending"}

    def pending(self, user_id):
        events = {e["id"]: e for e in self.events}
        out = []
        for row in self.outbox.values():
            event = events[row["event_id"]]
            if row["status"] != "pending" or event["user_id"] != user_id:
                continue
            card = self.card_ids.get(row["card_id"])
            out.append({
                "event_id": row["event_id"], "outcome": row["outcome"],
                "word_events": {"user_id": user_id, "occurred_at": event["occurred_at"]},
                "srs_cards": card and {"external_id": card[0], "srs_notes": {
                    "external_id": card[1],
                    "removed_at": "gone" if card[1] in self.removed_rems else None}},
            })
        return out

    def count_pending(self, user_id):
        return len(self.pending(user_id))

    def owned_pending(self, user_id, event_ids):
        events = {e["id"]: e for e in self.events}
        return {i for i in event_ids if i in self.outbox and self.outbox[i]["status"] == "pending"
                and events[i]["user_id"] == user_id}

    def decide(self, event_id, fields):
        if self.outbox[event_id]["status"] == "pending":
            self.outbox[event_id].update(fields)


def answers(*items):
    return PracticeRequest(language="es", answers=[
        PracticeAnswer(word=w, direction=d, correct=c) for w, d, c in items])


def test_every_answer_is_logged_and_unknown_words_are_reported():
    store = FakeStore()
    summary = record_practice(store, USER, answers(
        ("hablar", "recognize", True), ("Casa ", "produce", False), ("xyzzy", "recognize", True),
    ), now=NOW)

    assert (summary.recorded, summary.not_found) == (2, ["xyzzy"])
    assert [(e["word_id"], e["kind"], e["source"]) for e in store.events] == [
        (1, "recall_correct", "chatgpt"), (2, "recall_wrong", "chatgpt")]
    assert store.events[1]["context"] == {"direction": "produce"}


def test_direction_picks_the_card_and_grades_stay_conservative():
    store = FakeStore()
    summary = record_practice(store, USER, answers(
        ("hablar", "recognize", True),   # forward card 10
        ("hablar", "produce", False),    # backward card 11
    ), now=NOW)

    assert summary.queued == 2
    assert {r["card_id"]: r["outcome"] for r in store.outbox.values()} == {10: "good", 11: "again"}


def test_no_card_of_that_direction_means_no_outbox_row():
    # casa has a forward card and a cloze, no backward card; comer has no note.
    store = FakeStore()
    summary = record_practice(store, USER, answers(
        ("casa", "produce", True), ("comer", "recognize", False)), now=NOW)
    assert (summary.recorded, summary.queued, store.outbox) == (2, 0, {})


def test_within_one_call_a_wrong_answer_wins_and_one_row_per_card():
    store = FakeStore()
    record_practice(store, USER, answers(
        ("hablar", "recognize", True), ("hablar", "recognize", False), ("hablar", "recognize", True),
    ), now=NOW)

    assert len(store.events) == 3
    [row] = store.outbox.values()
    assert (row["card_id"], row["outcome"], row["event_id"]) == (10, "again", 2)


def test_a_card_takes_one_result_per_day():
    store = FakeStore()
    record_practice(store, USER, answers(("hablar", "recognize", True)), now=NOW)
    later = record_practice(store, USER, answers(("hablar", "recognize", False)),
                            now=NOW + timedelta(hours=2))
    tomorrow = record_practice(store, USER, answers(("hablar", "recognize", False)),
                               now=NOW + timedelta(days=1))

    assert (later.recorded, later.queued) == (1, 0)
    assert tomorrow.queued == 1


def test_langfour_scheduled_users_get_events_only():
    store = FakeStore(provider="langfour")
    summary = record_practice(store, USER, answers(("hablar", "recognize", False)), now=NOW)
    assert (summary.recorded, summary.queued, store.outbox) == (1, 0, {})


def test_pending_hands_out_remnote_ids_and_skips_rows_whose_card_is_gone():
    store = FakeStore()
    record_practice(store, USER, answers(("hablar", "recognize", True), ("casa", "recognize", False)),
                    now=NOW)
    store.removed_rems.add("r2")  # casa's Rem was deleted

    items = pending_practice(store, USER, now=NOW)

    assert [(i.card_id, i.rem_id, i.outcome) for i in items] == [("c10", "r1", "good")]
    assert store.outbox[2]["status"] == "skipped" and store.outbox[2]["reason"] == "card_gone"
    assert pending_practice(store, OTHER, now=NOW) == []


def test_reports_decide_own_pending_rows_once():
    store = FakeStore()
    record_practice(store, USER, answers(("hablar", "recognize", True), ("hablar", "produce", True)),
                    now=NOW)
    review_ms = int(NOW.timestamp() * 1000)
    report = PracticeReport(decisions=[
        PracticeDecision(event_id=1, status="applied", review_at=review_ms),
        PracticeDecision(event_id=2, status="skipped", reason="not_due"),
    ])

    assert report_practice(store, OTHER, report, now=NOW) == 0
    assert report_practice(store, USER, report, now=NOW) == 2
    assert report_practice(store, USER, report, now=NOW) == 0  # already decided

    assert store.outbox[1]["applied_review_at"] == NOW.isoformat()
    assert (store.outbox[2]["status"], store.outbox[2]["reason"]) == ("skipped", "not_due")


@pytest.mark.parametrize("status,review_at", [("applied", None), ("skipped", 1)])
def test_only_an_applied_decision_carries_a_review_date(status, review_at):
    with pytest.raises(ValidationError):
        PracticeDecision(event_id=1, status=status, review_at=review_at)


def test_a_session_is_capped():
    with pytest.raises(ValidationError):
        answers(*[("hablar", "recognize", True)] * 201)
