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
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import auth
import remnote_sync
from remnote_sync import (
    CardIn,
    NoteIn,
    PairingClaim,
    PushRequest,
    RelinkRequest,
    ReviewIn,
    apply_push,
    connection_status,
    hold_sync_lease,
    linked_words,
    normalize_code,
    pairing_approve,
    pairing_claim,
    pairing_info,
    pairing_start,
    pending_words,
    relink,
    review_outcome,
    sync_router,
)

USER = "user-1"
NOW = datetime(2026, 9, 26, tzinfo=UTC)
# Notes the fake creates are this old unless a test says otherwise, so the
# removal grace period does not get in the way of tests about removal.
LONG_AGO = (NOW - timedelta(days=30)).isoformat()
DAY_MS = 86_400_000
T0 = 1_780_000_000_000  # an arbitrary review time, in RemNote's unix ms


class FakeStore:
    """In-memory SyncStore with the database's uniqueness rules."""

    def __init__(self, userwords=(), translations=None):
        # userwords: (word_id, status, root, language, translation)
        self.userwords = list(userwords)
        self.translations = translations or {}
        self.notes: list[dict] = []
        self.cards: list[dict] = []
        self.reviews: dict[tuple, dict] = {}
        self._ids = iter(range(1, 10_000))
        self.note_created_at = LONG_AGO
        self.lease: tuple[str, datetime] | None = None
        self.clock = NOW
        self.token = None

    def owned_word_ids(self, user_id, word_ids):
        mine = {w[0] for w in self.userwords}
        return {w for w in word_ids if w in mine}

    def learning_words(self, user_id):
        return [{"word_id": w, "created_at": f"2026-0{1 + w % 9}-01T00:00:00+00:00",
                 "words": {"root": r, "language": lang, "translation": t}}
                for w, status, r, lang, t in self.userwords if status == "learning"]

    def word_details(self, user_id):
        return {w: {"language": lang, "added_at": f"2026-0{1 + w % 9}-01T00:00:00+00:00"}
                for w, _, _, lang, _ in self.userwords}

    def relink_note(self, note_id, rem_id):
        note = next(n for n in self.notes if n["id"] == note_id)
        note.update(external_id=rem_id, removed_at=None)

    def count_reviews(self, card_ids):
        return sum(1 for k in self.reviews if k[0] in card_ids)

    def custom_translations(self, user_id):
        return dict(self.translations)

    def notes_for_user(self, user_id):
        return [dict(n) for n in self.notes if n["user_id"] == user_id]

    def linked_rems(self, user_id, word_ids):
        return {n["word_id"]: n["external_id"] for n in self.notes if n["word_id"] in word_ids}

    def upsert_notes(self, rows):
        out = []
        for row in rows:
            clash = next((n for n in self.notes if n["external_id"] == row["external_id"]
                          and n["word_id"] != row["word_id"]), None)
            assert clash is None, "unique (user_id, provider, external_id) violated"
            note = next((n for n in self.notes if n["word_id"] == row["word_id"]), None)
            if note is None:
                note = {"id": next(self._ids), "created_at": self.note_created_at, **row}
                self.notes.append(note)
            else:
                note.update(row)
            out.append(dict(note))
        return out

    def set_removed(self, note_ids, removed_at):
        for n in self.notes:
            if n["id"] in note_ids:
                n["removed_at"] = removed_at

    def cards_for_notes(self, note_ids):
        return [dict(c) for c in self.cards if c["note_id"] in note_ids]

    def upsert_cards(self, rows):
        out = []
        for row in rows:
            card = next((c for c in self.cards if c["note_id"] == row["note_id"]
                         and c["external_id"] == row["external_id"]), None)
            if card is None:
                card = {"id": next(self._ids), **row}
                self.cards.append(card)
            else:
                card.update(row)
            out.append(dict(card))
        return out

    def delete_cards(self, card_ids):
        self.cards = [c for c in self.cards if c["id"] not in card_ids]
        self.reviews = {k: v for k, v in self.reviews.items() if k[0] not in card_ids}

    def move_words(self, user_id, word_ids, from_status, to_status):
        moved = 0
        for i, (w, status, *rest) in enumerate(self.userwords):
            if w in word_ids and status == from_status:
                self.userwords[i] = (w, to_status, *rest)
                moved += 1
        return moved

    def count_learning_words(self, user_id):
        return sum(1 for w in self.userwords if w[1] == "learning")

    def count_notes(self, user_id, *, active_only=False, learning_only=False):
        learning = {w[0] for w in self.userwords if w[1] == "learning"}
        return sum(1 for n in self.notes
                   if (not active_only or n["removed_at"] is None)
                   and (not learning_only or n["word_id"] in learning))

    def acquire_lease(self, user_id, holder, seconds):
        if self.lease and self.lease[0] != holder and self.lease[1] > self.clock:
            return False
        self.lease = (holder, self.clock + timedelta(seconds=seconds))
        return True

    def release_lease(self, user_id, holder):
        if self.lease and self.lease[0] == holder:
            self.lease = None

    # -- pairing and tokens (timestamps are ISO strings, as from PostgREST) --
    pairings: list

    def create_pairing(self, secret_hash, user_code, expires_at):
        self.pairings = getattr(self, "pairings", [])
        self.pairings.append({"id": f"p{len(self.pairings)}", "secret_hash": secret_hash,
                              "user_code": user_code, "user_id": None, "expires_at": expires_at})

    def delete_expired_pairings(self, now):
        self.pairings = [p for p in getattr(self, "pairings", []) if p["expires_at"] >= now]

    def count_live_pairings(self, now):
        return sum(p["expires_at"] > now for p in getattr(self, "pairings", []))

    def _live(self, now, **match):
        return next((dict(p) for p in getattr(self, "pairings", [])
                     if p["expires_at"] > now and all(p[k] == v for k, v in match.items())), None)

    def pairing_by_code(self, user_code, now):
        return self._live(now, user_code=user_code)

    def pairing_by_secret(self, secret_hash, now):
        return self._live(now, secret_hash=secret_hash)

    def approve_pairing(self, pairing_id, user_id, now):
        for p in self.pairings:
            if p["id"] == pairing_id and p["user_id"] is None and p["expires_at"] > now:
                p["user_id"] = user_id
                return True
        return False

    def take_pairing(self, pairing_id):
        before = len(self.pairings)
        self.pairings = [p for p in self.pairings if p["id"] != pairing_id]
        return len(self.pairings) < before

    def revoke_tokens(self, user_id, now):
        self.token = None

    def insert_token(self, user_id, token_hash):
        self.token = {"created_at": "now", "last_used_at": None, "hash": token_hash}

    def set_review_provider(self, user_id, provider):
        self.provider = provider

    def active_token(self, user_id):
        return self.token

    def insert_reviews(self, rows):
        new = [r for r in rows if (r["card_id"], r["reviewed_at"]) not in self.reviews]
        for row in new:
            self.reviews[(row["card_id"], row["reviewed_at"])] = row
        return len(new)


def card(card_id, kind="forward", scores=(), due=None):
    return CardIn(card_id=card_id, kind=kind, next_due_at=due,
                  reviews=[ReviewIn(at=T0 + i * DAY_MS, score=s)
                           for i, s in enumerate(scores)])


def spanish(*word_ids, status="learning"):
    return [(w, status, f"root{w}", "es", f"tr{w}") for w in word_ids]


# -- scores -----------------------------------------------------------------

@pytest.mark.parametrize("score,outcome", [
    (0, "again"), (0.5, "hard"), (1, "good"), (1.5, "easy"),
    (0.01, None), (2, None), (3, None), (4, None), (5, None),
])
def test_only_grading_scores_become_reviews(score, outcome):
    assert review_outcome(score) == outcome


def test_extra_fields_from_remnote_are_ignored():
    # RemNote sends isCram, responseTime, subQueueId...; only date and score matter.
    assert ReviewIn(at=T0, score=1, cram=True, responseTime=5).score == 1


# -- push -------------------------------------------------------------------

def test_push_records_notes_cards_and_graded_reviews():
    store = FakeStore(spanish(1))
    req = PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a", cards=[
        card("c-f", "forward", scores=(0, 1, 0.01), due=T0 + 5 * DAY_MS),
        card("c-b", "backward", scores=(1.5,)),
    ])])

    result = apply_push(store, USER, req, now=NOW)

    assert (result.notes, result.cards, result.reviews) == (1, 2, 3)
    assert store.notes[0]["external_id"] == "rem-a"
    forward = next(c for c in store.cards if c["external_id"] == "c-f")
    assert forward["next_due_at"].startswith("2026-")
    assert sorted(r["outcome"] for r in store.reviews.values()) == ["again", "easy", "good"]


def test_push_is_idempotent():
    store = FakeStore(spanish(1))
    req = PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a",
                                    cards=[card("c-f", scores=(0, 1))])])

    first = apply_push(store, USER, req, now=NOW)
    again = apply_push(store, USER, req, now=NOW)

    assert (len(store.notes), len(store.cards), len(store.reviews)) == (1, 1, 2)
    assert (first.reviews, again.reviews) == (2, 0)


def test_words_the_user_does_not_have_are_rejected():
    store = FakeStore(spanish(1))
    req = PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a"),
                             NoteIn(word_id=99, rem_id="rem-z")])

    result = apply_push(store, USER, req, now=NOW)

    assert result.rejected_word_ids == [99]
    assert [n["word_id"] for n in store.notes] == [1]


def test_one_rem_cannot_claim_two_words():
    store = FakeStore(spanish(1, 2))
    req = PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a"),
                             NoteIn(word_id=2, rem_id="rem-a")])

    result = apply_push(store, USER, req, now=NOW)

    assert result.rejected_word_ids == [2]
    assert len(store.notes) == 1


def test_a_second_rem_cannot_take_over_a_linked_word():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a",
                                                      cards=[card("c-a", scores=(1,))])]), now=NOW)

    result = apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-copy",
                                                               cards=[card("c-copy")])]), now=NOW)

    assert result.rejected_word_ids == [1]
    assert store.notes[0]["external_id"] == "rem-a"
    assert [c["external_id"] for c in store.cards] == ["c-a"]
    assert len(store.reviews) == 1


def test_the_linked_rem_wins_even_when_its_copy_comes_first():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a")]), now=NOW)

    apply_push(store, USER, PushRequest(notes=[
        NoteIn(word_id=1, rem_id="rem-copy", cards=[card("c-copy")]),
        NoteIn(word_id=1, rem_id="rem-a", cards=[card("c-a", scores=(1,))]),
    ]), now=NOW)

    assert store.notes[0]["external_id"] == "rem-a"
    assert [c["external_id"] for c in store.cards] == ["c-a"]


def test_a_card_missing_from_its_note_is_deleted_with_its_reviews():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a", cards=[
        card("c-f", "forward", scores=(1,)), card("c-b", "backward", scores=(0,)),
    ])]), now=NOW)

    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a", cards=[
        card("c-f", "forward", scores=(1,)),
    ])]), now=NOW)

    assert [c["external_id"] for c in store.cards] == ["c-f"]
    assert [r["outcome"] for r in store.reviews.values()] == ["good"]


def test_full_sweep_marks_missing_rems_removed_and_restores_returning_ones():
    store = FakeStore(spanish(1, 2))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a"),
                                               NoteIn(word_id=2, rem_id="rem-b")]), now=NOW)

    gone = apply_push(store, USER, PushRequest(present_rem_ids=["rem-a"]), now=NOW)
    assert gone.removed == 1
    assert next(n for n in store.notes if n["word_id"] == 2)["removed_at"] == NOW.isoformat()

    back = apply_push(store, USER, PushRequest(present_rem_ids=["rem-a", "rem-b"]), now=NOW)
    assert back.restored == 1
    assert all(n["removed_at"] is None for n in store.notes)


def test_a_just_created_note_survives_a_sweep_that_cannot_see_it_yet():
    # Device A created rem-b a minute ago; device B's RemNote has not synced
    # it yet, so B's sweep does not list it.
    store = FakeStore(spanish(1, 2))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a")]), now=NOW)
    store.note_created_at = (NOW - timedelta(minutes=1)).isoformat()
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=2, rem_id="rem-b")]), now=NOW)

    result = apply_push(store, USER, PushRequest(present_rem_ids=["rem-a"]), now=NOW)

    assert result.removed == 0
    assert all(n["removed_at"] is None for n in store.notes)


def test_a_partial_push_never_removes_anything():
    store = FakeStore(spanish(1, 2))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a"),
                                               NoteIn(word_id=2, rem_id="rem-b")]), now=NOW)

    result = apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a")]),
                        now=NOW)

    assert result.removed == 0
    assert all(n["removed_at"] is None for n in store.notes)


def test_turning_cards_off_in_remnote_disables_the_word_and_on_resumes_it():
    store = FakeStore(spanish(1, 2) + spanish(3, status="known"))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=w, rem_id=f"rem-{w}")
                                               for w in (1, 2, 3)]), now=NOW)
    every_rem = ["rem-1", "rem-2", "rem-3"]

    off = apply_push(store, USER, PushRequest(present_rem_ids=every_rem,
                                              disabled_rem_ids=["rem-1", "rem-3"]), now=NOW)
    # A known word stays known: turning its cards off says nothing about it.
    assert (off.disabled, off.enabled) == (1, 0)
    assert [s for _, s, *_ in store.userwords] == ["disabled", "learning", "known"]
    assert [p.word_id for p in pending_words(store, USER, 10).words] == []

    on = apply_push(store, USER, PushRequest(present_rem_ids=every_rem, disabled_rem_ids=[]),
                    now=NOW)
    assert (on.disabled, on.enabled) == (0, 1)
    assert [s for _, s, *_ in store.userwords] == ["learning", "learning", "known"]


def test_a_push_right_after_turning_cards_off_stops_the_word_at_once():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1")]), now=NOW)

    off = apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1",
                                                            practiced=False)]), now=NOW)
    assert off.disabled == 1 and store.userwords[0][1] == "disabled"

    on = apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1",
                                                           practiced=True)]), now=NOW)
    assert on.enabled == 1 and store.userwords[0][1] == "learning"


def test_turning_cards_off_never_deletes_their_history():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1",
                                                      cards=[card("c-f", scores=(1,))])]), now=NOW)

    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1", cards=[],
                                                      practiced=False)]), now=NOW)

    assert [c["external_id"] for c in store.cards] == ["c-f"]
    assert len(store.reviews) == 1


def test_a_deleted_rem_stops_its_word_and_restoring_it_resumes_it():
    store = FakeStore(spanish(1, 2))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1"),
                                               NoteIn(word_id=2, rem_id="rem-2")]), now=NOW)

    gone = apply_push(store, USER, PushRequest(present_rem_ids=["rem-1"],
                                               disabled_rem_ids=[]), now=NOW)
    assert (gone.removed, gone.disabled) == (1, 1)
    assert [s for _, s, *_ in store.userwords] == ["learning", "disabled"]

    back = apply_push(store, USER, PushRequest(present_rem_ids=["rem-1", "rem-2"],
                                               disabled_rem_ids=[]), now=NOW)
    assert (back.restored, back.enabled) == (1, 1)
    assert [s for _, s, *_ in store.userwords] == ["learning", "learning"]


def test_a_rem_deleted_before_this_change_stops_its_word_on_the_next_sweep():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1")]), now=NOW)
    store.notes[0]["removed_at"] = LONG_AGO

    result = apply_push(store, USER, PushRequest(present_rem_ids=[]), now=NOW)

    assert (result.removed, result.disabled) == (0, 1)


def test_a_sweep_without_practice_state_leaves_statuses_alone():
    # Older plugins send only present_rem_ids.
    store = FakeStore(spanish(1, status="disabled"))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-1")]), now=NOW)

    result = apply_push(store, USER, PushRequest(present_rem_ids=["rem-1"]), now=NOW)

    assert (result.disabled, result.enabled) == (0, 0)
    assert store.userwords[0][1] == "disabled"


# -- pending ----------------------------------------------------------------

def test_pending_offers_unlinked_learning_words_with_custom_translations():
    store = FakeStore(spanish(1, 2, 3) + spanish(4, status="known"),
                      translations={2: "my own"})
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a")]), now=NOW)

    result = pending_words(store, USER, limit=10)

    assert [(w.word_id, w.translation) for w in result.words] == [(2, "my own"), (3, "tr3")]
    assert result.remaining == 0


def test_a_removed_rem_is_not_offered_again():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a")]), now=NOW)
    apply_push(store, USER, PushRequest(present_rem_ids=[]), now=NOW)

    assert pending_words(store, USER, limit=10).words == []


def test_pending_reports_what_the_limit_held_back():
    store = FakeStore(spanish(1, 2, 3))

    result = pending_words(store, USER, limit=2)

    assert [w.word_id for w in result.words] == [1, 2]
    assert result.remaining == 1


# -- auth scoping -----------------------------------------------------------

@pytest.fixture
def verifiers(monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda t: "session-user")
    monkeypatch.setattr(auth, "verify_access_token", lambda t, p: f"token-user:{p}")


def test_sync_token_reaches_sync_paths(verifiers):
    assert auth._authenticate("lf_rn_abc", "/sync/remnote/push") == ("token-user:remnote_sync", None)


def test_sync_token_is_refused_everywhere_else(verifiers):
    user, error = auth._authenticate("lf_rn_abc", "/api/translate")
    assert user is None and "not valid" in error


def test_session_token_is_refused_on_sync_paths(verifiers):
    user, error = auth._authenticate("eyJ.session.jwt", "/sync/remnote/pending")
    assert user is None and "access token" in error


def test_session_token_still_works_elsewhere(verifiers):
    assert auth._authenticate("eyJ.session.jwt", "/integrations/remnote") == ("session-user", None)


def test_token_hash_is_stable_and_not_the_token():
    digest = auth.hash_access_token("lf_rn_secret")
    assert digest == auth.hash_access_token("lf_rn_secret")
    assert "secret" not in digest and len(digest) == 64


# -- sync lease -------------------------------------------------------------

def test_a_second_run_is_turned_away_while_the_first_holds_the_lease():
    store, user = FakeStore(), SimpleNamespace(id=USER)
    assert hold_sync_lease("run-aaaaaaaa", user, store) == "run-aaaaaaaa"
    # The holder renews freely.
    assert hold_sync_lease("run-aaaaaaaa", user, store) == "run-aaaaaaaa"

    with pytest.raises(HTTPException) as refused:
        hold_sync_lease("run-bbbbbbbb", user, store)
    assert refused.value.status_code == 423


def test_the_lease_passes_on_after_release_or_expiry():
    store, user = FakeStore(), SimpleNamespace(id=USER)
    hold_sync_lease("run-aaaaaaaa", user, store)
    store.release_lease(USER, "run-aaaaaaaa")
    assert hold_sync_lease("run-bbbbbbbb", user, store) == "run-bbbbbbbb"

    store.clock = NOW + timedelta(hours=1)  # run-bbbbbbbb died without releasing
    assert hold_sync_lease("run-cccccccc", user, store) == "run-cccccccc"


def test_every_plugin_request_of_a_run_holds_the_lease():
    # /linked is a run's first request, and the plugin rearranges Rems right
    # after it, so it must turn a second device away too. /release only hands
    # the lease back.
    for route in sync_router.routes:
        calls = {d.call for d in route.dependant.dependencies}
        assert (hold_sync_lease in calls) == (route.path != "/release"), route.path


# -- connection status ------------------------------------------------------

def test_status_counts_match_what_pending_would_hand_out():
    store = FakeStore(spanish(1, 2, 3, 4) + spanish(5, status="known"))
    store.token = {"created_at": "t", "last_used_at": None}
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a"),
                                               NoteIn(word_id=2, rem_id="rem-b")]), now=NOW)
    apply_push(store, USER, PushRequest(present_rem_ids=["rem-a"]), now=NOW)  # rem-b deleted

    status = connection_status(SimpleNamespace(id=USER), store)

    pending = pending_words(store, USER, limit=100)
    assert status.pending_words == len(pending.words) == 2
    assert status.linked_words == 1


def test_status_skips_the_pending_count_without_a_token():
    status = connection_status(SimpleNamespace(id=USER), FakeStore(spanish(1)))
    assert (status.connected, status.pending_words) == (False, 0)


# -- pairing ----------------------------------------------------------------

ALICE, MALLORY = SimpleNamespace(id="alice"), SimpleNamespace(id="mallory")


def test_pairing_hands_the_token_to_the_plugin_only_after_approval():
    store = FakeStore()
    started = pairing_start(store)
    assert started.verify_url.endswith(f"/connect/remnote?code={started.user_code}")

    waiting = pairing_claim(PairingClaim(secret=started.secret), store)
    assert waiting.status_code == 202

    assert pairing_info(started.user_code.lower().replace("-", ""), ALICE, store).user_code == started.user_code
    pairing_approve(started.user_code, ALICE, store)
    issued = pairing_claim(PairingClaim(secret=started.secret), store)

    assert issued["token"].startswith("lf_rn_")
    assert store.token["hash"] == auth.hash_access_token(issued["token"])
    assert store.provider == "remnote"


def test_a_pairing_is_collected_once():
    store = FakeStore()
    started = pairing_start(store)
    pairing_approve(started.user_code, ALICE, store)
    pairing_claim(PairingClaim(secret=started.secret), store)

    with pytest.raises(HTTPException) as again:
        pairing_claim(PairingClaim(secret=started.secret), store)
    assert again.value.status_code == 404


def test_a_code_approved_by_one_user_cannot_be_taken_over():
    store = FakeStore()
    started = pairing_start(store)
    pairing_approve(started.user_code, ALICE, store)
    pairing_approve(started.user_code, ALICE, store)  # approving twice is harmless

    for call in (pairing_approve, pairing_info):
        with pytest.raises(HTTPException) as refused:
            call(started.user_code, MALLORY, store)
        assert refused.value.status_code == 404


def test_an_expired_pairing_cannot_be_approved_or_claimed():
    store = FakeStore()
    started = pairing_start(store)
    store.pairings[0]["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    with pytest.raises(HTTPException):
        pairing_approve(started.user_code, ALICE, store)
    with pytest.raises(HTTPException):
        pairing_claim(PairingClaim(secret=started.secret), store)


def test_a_wrong_secret_gets_nothing():
    store = FakeStore()
    started = pairing_start(store)
    pairing_approve(started.user_code, ALICE, store)

    with pytest.raises(HTTPException):
        pairing_claim(PairingClaim(secret="x" * 43), store)


def test_pairings_are_capped_until_old_ones_expire(monkeypatch):
    monkeypatch.setattr(remnote_sync, "MAX_LIVE_PAIRINGS", 2)
    store = FakeStore()
    pairing_start(store)
    pairing_start(store)
    with pytest.raises(HTTPException) as refused:
        pairing_start(store)
    assert refused.value.status_code == 429

    for p in store.pairings:  # ten minutes later
        p["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert pairing_start(store).user_code


@pytest.mark.parametrize("raw", ["kfpm2931", "KFPM-2931", " kfpm 2931 "])
def test_codes_are_normalised(raw):
    assert normalize_code(raw) == "KFPM-2931"


def test_pairing_paths_are_public_and_nothing_else_new_is():
    assert {"/pair/remnote/start", "/pair/remnote/claim"} <= auth.PUBLIC_PATHS
    assert not any(p.startswith(("/sync/", "/integrations/")) for p in auth.PUBLIC_PATHS)


def test_a_failed_token_lookup_is_unavailable_not_unauthorised(monkeypatch):
    class Broken:
        def table(self, name):
            raise ConnectionError("database unreachable")

    monkeypatch.setattr(auth, "_supabase", Broken())
    with pytest.raises(auth.AuthUnavailable):
        auth.verify_access_token("lf_rn_not-cached", "remnote_sync")


# -- linked words and relinking ---------------------------------------------

def test_linked_words_carry_language_and_save_date_for_live_notes_only():
    store = FakeStore(spanish(1, 2))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-a"),
                                               NoteIn(word_id=2, rem_id="rem-b")]), now=NOW)
    apply_push(store, USER, PushRequest(present_rem_ids=["rem-a"]), now=NOW)  # rem-b deleted

    words = linked_words(store, USER).words

    assert [(w.word_id, w.language) for w in words] == [(1, "es")]
    assert words[0].added_at.startswith("2026-")


def test_pending_words_carry_their_save_date():
    store = FakeStore(spanish(1))
    assert pending_words(store, USER, limit=10).words[0].added_at.startswith("2026-")


def test_an_unreviewed_copy_can_be_relinked_to_an_existing_flashcard():
    store = FakeStore(spanish(1))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-copy",
                                                      cards=[card("c-copy")])]), now=NOW)

    relink(store, USER, RelinkRequest(word_id=1, from_rem_id="rem-copy", to_rem_id="rem-mine"))

    assert store.notes[0]["external_id"] == "rem-mine"
    assert store.cards == []  # the copy's cards are gone; the next push brings the real ones


@pytest.mark.parametrize("reason,setup,req", [
    ("wrong source", lambda s: None, {"word_id": 1, "from_rem_id": "rem-other", "to_rem_id": "rem-mine"}),
    ("target taken", lambda s: None, {"word_id": 1, "from_rem_id": "rem-copy", "to_rem_id": "rem-2"}),
    ("copy was reviewed", lambda s: apply_push(s, USER, PushRequest(notes=[NoteIn(
        word_id=1, rem_id="rem-copy", cards=[card("c-copy", scores=(1,))])]), now=NOW),
     {"word_id": 1, "from_rem_id": "rem-copy", "to_rem_id": "rem-mine"}),
])
def test_relinking_is_refused_when_it_could_lose_or_steal_data(reason, setup, req):
    store = FakeStore(spanish(1, 2))
    apply_push(store, USER, PushRequest(notes=[NoteIn(word_id=1, rem_id="rem-copy"),
                                               NoteIn(word_id=2, rem_id="rem-2")]), now=NOW)
    setup(store)

    with pytest.raises(HTTPException) as refused:
        relink(store, USER, RelinkRequest(**req))
    assert refused.value.status_code == 409, reason
