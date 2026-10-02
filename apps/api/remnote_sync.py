"""
RemNote sync: Langfour decides which words to learn, RemNote schedules them.

Three routers, three kinds of caller (auth.py enforces the split):

  /pair/remnote          the RemNote plugin before it has a token. No auth:
                         `start` opens a pairing, `claim` collects the token
                         once the user approved it.
  /integrations/remnote  the web app, with the user's Supabase session.
                         Approves pairings, shows the connection, disconnects.
  /sync/remnote          the RemNote plugin, with its access token.
                         `pending` hands out learning words that have no Rem
                         yet; `push` records which Rem and cards the plugin
                         made and the reviews RemNote graded.

Pairing is the OAuth device flow (RFC 8628) in miniature: the plugin shows a
short code and opens Langfour, the signed-in user approves that code, and the
plugin collects a token with a secret only it holds. Nothing is copied by
hand, and the token exists only from the moment the plugin collects it.

Storage is sql/remnote_sync.sql. The plugin is the only writer and resends an
overlapping window of history on every sync, so every write here is an
idempotent upsert keyed on RemNote's own ids.
"""

import logging
import os
import secrets
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import get_current_user, hash_access_token
from supabase_client import supabase

logger = logging.getLogger(__name__)

PROVIDER = "remnote"
TOKEN_PURPOSE = "remnote_sync"
TOKEN_PREFIX = "lf_rn_"  # must match auth.ACCESS_TOKEN_SCOPES

# Where the user approves a pairing. Local development points this at the
# local web app.
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://app.langfour.com").rstrip("/")
PAIRING_TTL = timedelta(minutes=10)
PAIRING_POLL_SECONDS = 3
# `start` needs no sign-in and writes a row, so cap how many can be live at
# once: a flood is turned away instead of growing the table. Real use is a
# handful a day. A cap rather than a per-IP limit, since behind the proxy the
# client address is a header anyone can set.
MAX_LIVE_PAIRINGS = 100
# No 0/O or 1/I/L: the code is read off one screen and checked on another.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# One sync at a time per user, across every device. A run renews the lease on
# each request; a run that dies simply lets it lapse.
LEASE_SECONDS = 300

# A Rem made by another device reaches this one only after RemNote syncs it,
# so a sweep may not see it yet. Notes this young are never marked removed.
REMOVAL_GRACE = timedelta(days=1)

# PostgREST caps a response at 1000 rows, and `in` filters travel in the URL.
_PAGE = 1000
_IN_CHUNK = 200

web_router = APIRouter()
sync_router = APIRouter()
pair_router = APIRouter()


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class ReviewIn(BaseModel):
    at: int = Field(..., description="Unix time in milliseconds, as RemNote reports it")
    score: float = Field(..., description="RemNote QueueInteractionScore")


class CardIn(BaseModel):
    card_id: str = Field(..., min_length=1, max_length=64)
    kind: Literal["forward", "backward", "cloze"]
    next_due_at: int | None = Field(None, description="Unix ms; null if unscheduled")
    reviews: list[ReviewIn] = Field(default_factory=list, max_length=10_000)


class NoteIn(BaseModel):
    word_id: int
    rem_id: str = Field(..., min_length=1, max_length=64)
    # The complete set of cards the Rem has now: cards missing here are gone.
    cards: list[CardIn] = Field(default_factory=list, max_length=50)


class PushRequest(BaseModel):
    notes: list[NoteIn] = Field(default_factory=list, max_length=500)
    # Every Rem the plugin still sees, sent once at the end of a sync. A note
    # whose Rem is missing is marked removed; null means "not a full sweep".
    present_rem_ids: list[str] | None = Field(None, max_length=100_000)


class PushResponse(BaseModel):
    notes: int
    cards: int
    reviews: int  # newly recorded; resent ones are not counted again
    removed: int
    restored: int
    rejected_word_ids: list[int]


class PendingWord(BaseModel):
    word_id: int
    root: str
    language: str
    translation: str | None
    added_at: str  # when the user saved the word; the plugin files it by month


class LinkedWord(BaseModel):
    word_id: int
    language: str
    added_at: str


class LinkedResponse(BaseModel):
    words: list[LinkedWord]


class RelinkRequest(BaseModel):
    word_id: int
    from_rem_id: str = Field(..., min_length=1, max_length=64)
    to_rem_id: str = Field(..., min_length=1, max_length=64)


class PendingResponse(BaseModel):
    words: list[PendingWord]
    remaining: int


class ConnectionStatus(BaseModel):
    connected: bool
    token_created_at: str | None
    token_last_used_at: str | None
    linked_words: int
    pending_words: int


# ---------------------------------------------------------------------------
# RemNote's QueueInteractionScore. Only the four grades are answers;
# TOO_EARLY (0.01), VIEWED_AS_LEECH (2), RESET (3), MANUAL_DATE (4) and
# MANUAL_EASE (5) are bookkeeping. RemNote's isCram flag is not a filter: it
# is set on reviews practised from a document's Due button, which do move the
# schedule, so every graded answer counts.
# ---------------------------------------------------------------------------
REMNOTE_OUTCOMES = {0.0: "again", 0.5: "hard", 1.0: "good", 1.5: "easy"}


def review_outcome(score: float) -> str | None:
    return REMNOTE_OUTCOMES.get(float(score))


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _chunks(items: list, size: int = _IN_CHUNK) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _select_all(build: Callable) -> list[dict]:
    """Page through a select. `build` returns a fresh query each time, because
    a postgrest builder cannot be reused after execute()."""
    rows, start = [], 0
    while True:
        page = build().range(start, start + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        start += _PAGE


# ---------------------------------------------------------------------------
# Storage. Everything that touches Supabase lives on this class, so the sync
# logic below can be tested against an in-memory stand-in.
# ---------------------------------------------------------------------------

class SyncStore:
    def __init__(self, client):
        self.db = client

    # -- words ------------------------------------------------------------
    def owned_word_ids(self, user_id: str, word_ids: list[int]) -> set[int]:
        owned: set[int] = set()
        for chunk in _chunks(word_ids):
            res = (self.db.table("userwords").select("word_id")
                   .eq("user_id", user_id).in_("word_id", chunk).execute())
            owned.update(r["word_id"] for r in res.data or [])
        return owned

    def learning_words(self, user_id: str) -> list[dict]:
        """Oldest first, with the dictionary entry embedded."""
        return _select_all(lambda: (
            self.db.table("userwords")
            .select("word_id, created_at, words(root, language, translation)")
            .eq("user_id", user_id).eq("status", "learning")
            .order("created_at").order("word_id")
        ))

    def word_details(self, user_id: str) -> dict[int, dict]:
        """word_id -> {language, added_at} for every word the user has."""
        rows = _select_all(lambda: (
            self.db.table("userwords").select("word_id, created_at, words(language)")
            .eq("user_id", user_id).order("word_id")
        ))
        return {r["word_id"]: {"language": r["words"]["language"], "added_at": r["created_at"]}
                for r in rows if r.get("words")}

    def custom_translations(self, user_id: str) -> dict[int, str]:
        rows = _select_all(lambda: (
            self.db.table("usertranslations")
            .select("word_id, custom_translation")
            .eq("user_id", user_id).order("created_at")
        ))
        # Ordered oldest first, so the latest translation for a word wins.
        return {r["word_id"]: r["custom_translation"] for r in rows}

    def count_learning_words(self, user_id: str) -> int:
        res = (self.db.table("userwords").select("word_id", count="exact")
               .eq("user_id", user_id).eq("status", "learning").limit(1).execute())
        return res.count or 0

    # -- notes ------------------------------------------------------------
    def notes_for_user(self, user_id: str) -> list[dict]:
        return _select_all(lambda: (
            self.db.table("srs_notes").select("id, word_id, external_id, created_at, removed_at")
            .eq("user_id", user_id).eq("provider", PROVIDER).order("id")
        ))

    def count_notes(self, user_id: str, *, active_only: bool = False,
                    learning_only: bool = False) -> int:
        # The inner embed filters notes by their word's status through the
        # composite FK to userwords.
        columns = "id, userwords!inner(status)" if learning_only else "id"
        query = (self.db.table("srs_notes").select(columns, count="exact")
                 .eq("user_id", user_id).eq("provider", PROVIDER))
        if active_only:
            query = query.is_("removed_at", "null")
        if learning_only:
            query = query.eq("userwords.status", "learning")
        return query.limit(1).execute().count or 0

    def linked_rems(self, user_id: str, word_ids: list[int]) -> dict[int, str]:
        """word_id -> the Rem its note points at, for words that have a note."""
        linked: dict[int, str] = {}
        for chunk in _chunks(word_ids):
            res = (self.db.table("srs_notes").select("word_id, external_id")
                   .eq("user_id", user_id).eq("provider", PROVIDER)
                   .in_("word_id", chunk).execute())
            linked.update((r["word_id"], r["external_id"]) for r in res.data or [])
        return linked

    def upsert_notes(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        res = (self.db.table("srs_notes")
               .upsert(rows, on_conflict="user_id,provider,word_id").execute())
        return res.data or []

    def relink_note(self, note_id: int, rem_id: str) -> None:
        (self.db.table("srs_notes").update({"external_id": rem_id, "removed_at": None})
         .eq("id", note_id).execute())

    def set_removed(self, note_ids: list[int], removed_at: str | None) -> None:
        for chunk in _chunks(note_ids):
            (self.db.table("srs_notes").update({"removed_at": removed_at})
             .in_("id", chunk).execute())

    # -- cards ------------------------------------------------------------
    def cards_for_notes(self, note_ids: list[int]) -> list[dict]:
        rows: list[dict] = []
        for chunk in _chunks(note_ids):
            res = (self.db.table("srs_cards").select("id, note_id, external_id")
                   .in_("note_id", chunk).execute())
            rows.extend(res.data or [])
        return rows

    def upsert_cards(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        res = (self.db.table("srs_cards")
               .upsert(rows, on_conflict="note_id,external_id").execute())
        return res.data or []

    def delete_cards(self, card_ids: list[int]) -> None:
        for chunk in _chunks(card_ids):
            self.db.table("srs_cards").delete().in_("id", chunk).execute()

    # -- reviews ----------------------------------------------------------
    def count_reviews(self, card_ids: list[int]) -> int:
        total = 0
        for chunk in _chunks(card_ids):
            res = (self.db.table("srs_reviews").select("card_id", count="exact")
                   .in_("card_id", chunk).limit(1).execute())
            total += res.count or 0
        return total

    def insert_reviews(self, rows: list[dict]) -> int:
        """Returns how many were new: ON CONFLICT DO NOTHING returns only the
        rows it inserted."""
        inserted = 0
        for chunk in _chunks(rows, 1000):
            res = (self.db.table("srs_reviews")
                   .upsert(chunk, on_conflict="card_id,reviewed_at", ignore_duplicates=True)
                   .execute())
            inserted += len(res.data or [])
        return inserted

    # -- sync lease -------------------------------------------------------
    def acquire_lease(self, user_id: str, holder: str, seconds: int) -> bool:
        """Take or renew the user's sync lease. Atomic in the database: the
        function's conditional upsert grants it only to the current holder or
        once the previous holder's lease has expired."""
        res = self.db.rpc("srs_acquire_sync_lease", {
            "p_user_id": user_id, "p_holder": holder, "p_seconds": seconds,
        }).execute()
        return bool(res.data)

    def release_lease(self, user_id: str, holder: str) -> None:
        (self.db.table("srs_sync_leases").delete()
         .eq("user_id", user_id).eq("holder", holder).execute())

    # -- pairing ------------------------------------------------------------
    def create_pairing(self, secret_hash: str, user_code: str, expires_at: str) -> None:
        self.db.table("api_token_pairings").insert({
            "purpose": TOKEN_PURPOSE, "secret_hash": secret_hash,
            "user_code": user_code, "expires_at": expires_at,
        }).execute()

    def delete_expired_pairings(self, now: str) -> None:
        self.db.table("api_token_pairings").delete().lt("expires_at", now).execute()

    def count_live_pairings(self, now: str) -> int:
        res = (self.db.table("api_token_pairings").select("id", count="exact")
               .gt("expires_at", now).limit(1).execute())
        return res.count or 0

    def pairing_by_code(self, user_code: str, now: str) -> dict | None:
        res = (self.db.table("api_token_pairings").select("id, user_code, user_id, expires_at")
               .eq("user_code", user_code).gt("expires_at", now).limit(1).execute())
        return (res.data or [None])[0]

    def pairing_by_secret(self, secret_hash: str, now: str) -> dict | None:
        res = (self.db.table("api_token_pairings").select("id, user_id, expires_at")
               .eq("secret_hash", secret_hash).gt("expires_at", now).limit(1).execute())
        return (res.data or [None])[0]

    def approve_pairing(self, pairing_id: str, user_id: str, now: str) -> bool:
        """Compare-and-set: only a pending, unexpired pairing can be approved,
        and only once."""
        res = (self.db.table("api_token_pairings")
               .update({"user_id": user_id, "approved_at": now})
               .eq("id", pairing_id).is_("user_id", "null").gt("expires_at", now)
               .execute())
        return bool(res.data)

    def take_pairing(self, pairing_id: str) -> bool:
        """Delete and report whether this call was the one that deleted it, so
        two concurrent claims cannot both mint a token."""
        res = self.db.table("api_token_pairings").delete().eq("id", pairing_id).execute()
        return bool(res.data)

    # -- connection -------------------------------------------------------
    def active_token(self, user_id: str) -> dict | None:
        res = (self.db.table("api_tokens").select("created_at, last_used_at")
               .eq("user_id", user_id).eq("purpose", TOKEN_PURPOSE)
               .is_("revoked_at", "null").limit(1).execute())
        return (res.data or [None])[0]

    def revoke_tokens(self, user_id: str, now: str) -> None:
        (self.db.table("api_tokens").update({"revoked_at": now})
         .eq("user_id", user_id).eq("purpose", TOKEN_PURPOSE)
         .is_("revoked_at", "null").execute())

    def insert_token(self, user_id: str, token_hash: str) -> None:
        self.db.table("api_tokens").insert({
            "user_id": user_id, "purpose": TOKEN_PURPOSE, "token_hash": token_hash,
        }).execute()

    def set_review_provider(self, user_id: str, provider: str) -> None:
        (self.db.table("userdata").update({"review_provider": provider})
         .eq("user_id", user_id).execute())


def get_store() -> SyncStore:
    return SyncStore(supabase)


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def pending_words(store: SyncStore, user_id: str, limit: int) -> PendingResponse:
    """Learning words that have never had a Rem. A word whose Rem was deleted
    keeps its (removed) note, so it is not offered again."""
    linked = {n["word_id"] for n in store.notes_for_user(user_id)}
    todo = [r for r in store.learning_words(user_id)
            if r["word_id"] not in linked and r.get("words")]
    custom = store.custom_translations(user_id) if todo else {}

    words = [
        PendingWord(
            word_id=r["word_id"],
            root=r["words"]["root"],
            language=r["words"]["language"],
            translation=custom.get(r["word_id"]) or r["words"].get("translation"),
            added_at=r["created_at"],
        )
        for r in todo[:limit]
    ]
    return PendingResponse(words=words, remaining=max(0, len(todo) - len(words)))


def linked_words(store: SyncStore, user_id: str) -> LinkedResponse:
    """Language and save date of every word that has a Rem. The plugin keeps
    neither on the Rem itself, so it asks here."""
    details = store.word_details(user_id)
    return LinkedResponse(words=[
        LinkedWord(word_id=n["word_id"], **details[n["word_id"]])
        for n in store.notes_for_user(user_id)
        if n["removed_at"] is None and n["word_id"] in details
    ])


def relink(store: SyncStore, user_id: str, req: RelinkRequest) -> None:
    """Move a word from the Rem the plugin created to a flashcard the user
    already had. The only way a note changes Rem: apply_push refuses it, since
    a silent takeover would delete the first Rem's cards and reviews. Here the
    plugin names both Rems, and the created one must never have been reviewed.
    """
    notes = store.notes_for_user(user_id)
    note = next((n for n in notes if n["word_id"] == req.word_id), None)
    if note is None or note["external_id"] != req.from_rem_id:
        raise HTTPException(status_code=409, detail="The word is not linked to that Rem.")
    if any(n["external_id"] == req.to_rem_id for n in notes):
        raise HTTPException(status_code=409, detail="That Rem already holds another word.")
    card_ids = [c["id"] for c in store.cards_for_notes([note["id"]])]
    if store.count_reviews(card_ids):
        raise HTTPException(status_code=409, detail="The linked Rem has reviews; keeping it.")
    store.delete_cards(card_ids)
    store.relink_note(note["id"], req.to_rem_id)


def apply_push(store: SyncStore, user_id: str, req: PushRequest,
               now: datetime | None = None) -> PushResponse:
    now_iso = (now or datetime.now(UTC)).isoformat()

    # Refused, per note: a word the user does not have (the composite FK would
    # fail the whole batch instead); a second Rem for a word already linked to
    # another (a copied Rem, or two devices creating one each), since taking
    # over the note would delete the first Rem's cards and their reviews; and
    # a second note for the same word or Rem within this push.
    owned = store.owned_word_ids(user_id, list({n.word_id for n in req.notes}))
    linked = store.linked_rems(user_id, list(owned))
    notes: dict[int, NoteIn] = {}
    seen_rems: set[str] = set()
    rejected: set[int] = set()
    for note in req.notes:
        if (note.word_id not in owned
                or linked.get(note.word_id, note.rem_id) != note.rem_id
                or note.word_id in notes or note.rem_id in seen_rems):
            rejected.add(note.word_id)
            continue
        notes[note.word_id] = note
        seen_rems.add(note.rem_id)

    saved = store.upsert_notes([
        {"user_id": user_id, "word_id": w, "provider": PROVIDER,
         "external_id": n.rem_id, "removed_at": None}
        for w, n in notes.items()
    ])
    note_id_by_word = {r["word_id"]: r["id"] for r in saved}

    # A note's card list is complete, so a card RemNote no longer has (the
    # user switched a Rem from both directions to one) is deleted with its
    # reviews rather than left to look forever overdue.
    card_rows: list[dict] = []
    for word_id, note_id in note_id_by_word.items():
        for card in notes[word_id].cards:
            card_rows.append({
                "note_id": note_id,
                "external_id": card.card_id,
                "kind": card.kind,
                "next_due_at": _ms_to_iso(card.next_due_at) if card.next_due_at else None,
            })
    wanted = {(c["note_id"], c["external_id"]) for c in card_rows}
    stale = [c["id"] for c in store.cards_for_notes(list(note_id_by_word.values()))
             if (c["note_id"], c["external_id"]) not in wanted]
    store.delete_cards(stale)

    saved_cards = store.upsert_cards(card_rows)
    card_id_by_key = {(c["note_id"], c["external_id"]): c["id"] for c in saved_cards}

    reviews: dict[tuple[int, str], dict] = {}
    for word_id, note_id in note_id_by_word.items():
        for card in notes[word_id].cards:
            card_id = card_id_by_key.get((note_id, card.card_id))
            if card_id is None:
                continue
            for review in card.reviews:
                outcome = review_outcome(review.score)
                if outcome is None:
                    continue
                at = _ms_to_iso(review.at)
                reviews[(card_id, at)] = {"card_id": card_id, "reviewed_at": at,
                                          "outcome": outcome}
    new_reviews = store.insert_reviews(list(reviews.values()))

    removed = restored = 0
    if req.present_rem_ids is not None:
        present = set(req.present_rem_ids)
        settled_before = (now or datetime.now(UTC)) - REMOVAL_GRACE
        existing = store.notes_for_user(user_id)
        gone = [n["id"] for n in existing
                if n["external_id"] not in present and n["removed_at"] is None
                and datetime.fromisoformat(n["created_at"]) < settled_before]
        back = [n["id"] for n in existing
                if n["external_id"] in present and n["removed_at"] is not None]
        store.set_removed(gone, now_iso)
        store.set_removed(back, None)
        removed, restored = len(gone), len(back)

    return PushResponse(
        notes=len(saved),
        cards=len(saved_cards),
        reviews=new_reviews,
        removed=removed,
        restored=restored,
        rejected_word_ids=sorted(rejected),
    )


# ---------------------------------------------------------------------------
# Plugin endpoints (access token)
# ---------------------------------------------------------------------------

def hold_sync_lease(
    x_sync_run: str = Header(..., min_length=8, max_length=64),
    user=Depends(get_current_user),
    store: SyncStore = Depends(get_store),
) -> str:
    """Every plugin request names its sync run. Two runs at once would both be
    handed the same pending words and both create a Rem for each, so a second
    run is turned away until the first releases the lease or stops renewing it."""
    if not store.acquire_lease(str(user.id), x_sync_run, LEASE_SECONDS):
        # 423, not 409: 409 means a refused change (relink), which the plugin
        # handles per word; 423 means "come back later" for the whole run.
        raise HTTPException(status_code=423, detail="Another sync is running")
    return x_sync_run


@sync_router.get("/pending", response_model=PendingResponse)
def sync_pending(
    limit: int = Query(200, ge=1, le=1000),
    _run: str = Depends(hold_sync_lease),
    user=Depends(get_current_user),
    store: SyncStore = Depends(get_store),
):
    return pending_words(store, str(user.id), limit)


@sync_router.post("/push", response_model=PushResponse)
def sync_push(
    req: PushRequest,
    _run: str = Depends(hold_sync_lease),
    user=Depends(get_current_user),
    store: SyncStore = Depends(get_store),
):
    return apply_push(store, str(user.id), req)


@sync_router.get("/linked", response_model=LinkedResponse)
def sync_linked(
    _run: str = Depends(hold_sync_lease),
    user=Depends(get_current_user),
    store: SyncStore = Depends(get_store),
):
    # Leased although it only reads: it is a run's first request, and the
    # plugin starts rearranging Rems right after it, so a second device must
    # be turned away here rather than at /pending.
    return linked_words(store, str(user.id))


@sync_router.post("/relink", status_code=204)
def sync_relink(
    req: RelinkRequest,
    _run: str = Depends(hold_sync_lease),
    user=Depends(get_current_user),
    store: SyncStore = Depends(get_store),
):
    relink(store, str(user.id), req)


@sync_router.post("/release", status_code=204)
def sync_release(
    x_sync_run: str = Header(..., min_length=8, max_length=64),
    user=Depends(get_current_user),
    store: SyncStore = Depends(get_store),
):
    store.release_lease(str(user.id), x_sync_run)


# ---------------------------------------------------------------------------
# Web app endpoints (Supabase session)
# ---------------------------------------------------------------------------

@web_router.get("", response_model=ConnectionStatus)
def connection_status(user=Depends(get_current_user), store: SyncStore = Depends(get_store)):
    user_id = str(user.id)
    token = store.active_token(user_id)
    # Counts only, no rows: learning words minus those that already have a
    # note (a removed note included, since that word is not offered again).
    # Nothing syncs without a token, so the pending count is skipped then.
    pending = (store.count_learning_words(user_id) - store.count_notes(user_id, learning_only=True)
               if token else 0)
    return ConnectionStatus(
        connected=token is not None,
        token_created_at=token and token["created_at"],
        token_last_used_at=token and token["last_used_at"],
        linked_words=store.count_notes(user_id, active_only=True),
        pending_words=max(0, pending),
    )


class PairingStart(BaseModel):
    user_code: str
    secret: str
    verify_url: str
    expires_in: int
    poll_interval: int


class PairingClaim(BaseModel):
    secret: str = Field(..., min_length=20, max_length=200)


class PairingInfo(BaseModel):
    user_code: str
    expires_at: str


def normalize_code(raw: str) -> str:
    code = "".join(c for c in raw.upper() if c.isalnum())
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code


def issue_token(store: SyncStore, user_id: str, now: str) -> str:
    """A new plugin token, replacing any previous one. The plaintext leaves
    here exactly once; only its hash is stored."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    store.revoke_tokens(user_id, now)
    store.insert_token(user_id, hash_access_token(token))
    store.set_review_provider(user_id, PROVIDER)
    return token


# -- plugin, before it has a token (public paths in auth.py) -----------------

@pair_router.post("/start", response_model=PairingStart)
def pairing_start(store: SyncStore = Depends(get_store)):
    now = datetime.now(UTC)
    store.delete_expired_pairings(now.isoformat())
    if store.count_live_pairings(now.isoformat()) >= MAX_LIVE_PAIRINGS:
        raise HTTPException(status_code=429, detail="Too many connection attempts right now. Try again in a few minutes.")
    secret = secrets.token_urlsafe(32)
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    user_code = f"{code[:4]}-{code[4:]}"
    store.create_pairing(hash_access_token(secret), user_code, (now + PAIRING_TTL).isoformat())
    return PairingStart(
        user_code=user_code,
        secret=secret,
        verify_url=f"{WEB_APP_URL}/connect/remnote?code={user_code}",
        expires_in=int(PAIRING_TTL.total_seconds()),
        poll_interval=PAIRING_POLL_SECONDS,
    )


@pair_router.post("/claim")
def pairing_claim(req: PairingClaim, store: SyncStore = Depends(get_store)):
    """202 while the user has not approved yet; the token once they have; 404
    once the pairing expired or was already collected."""
    now = datetime.now(UTC).isoformat()
    pairing = store.pairing_by_secret(hash_access_token(req.secret), now)
    if pairing is None:
        raise HTTPException(status_code=404, detail="This pairing expired. Start again.")
    if pairing["user_id"] is None:
        return JSONResponse(status_code=202, content={"status": "pending"})
    if not store.take_pairing(pairing["id"]):
        raise HTTPException(status_code=404, detail="This pairing was already used.")
    return {"token": issue_token(store, pairing["user_id"], now)}


# -- web app: the signed-in user approves ------------------------------------

@web_router.get("/pairings/{code}", response_model=PairingInfo)
def pairing_info(code: str, user=Depends(get_current_user), store: SyncStore = Depends(get_store)):
    pairing = store.pairing_by_code(normalize_code(code), datetime.now(UTC).isoformat())
    if pairing is None or pairing["user_id"] not in (None, str(user.id)):
        raise HTTPException(status_code=404, detail="This code has expired or does not exist.")
    return PairingInfo(user_code=pairing["user_code"], expires_at=pairing["expires_at"])


@web_router.post("/pairings/{code}/approve", status_code=204)
def pairing_approve(code: str, user=Depends(get_current_user), store: SyncStore = Depends(get_store)):
    now = datetime.now(UTC).isoformat()
    pairing = store.pairing_by_code(normalize_code(code), now)
    if pairing is None:
        raise HTTPException(status_code=404, detail="This code has expired or does not exist.")
    if pairing["user_id"] == str(user.id):
        return  # approved already; approving twice is harmless
    if not store.approve_pairing(pairing["id"], str(user.id), now):
        raise HTTPException(status_code=404, detail="This code has expired or was already used.")


@web_router.delete("/token", status_code=204)
def revoke_token(user=Depends(get_current_user), store: SyncStore = Depends(get_store)):
    """Disconnect: the token stops working and reviews move back to Langfour.
    The sync history is kept, so reconnecting later does not duplicate Rems."""
    user_id = str(user.id)
    store.revoke_tokens(user_id, datetime.now(UTC).isoformat())
    store.set_review_provider(user_id, "langfour")
