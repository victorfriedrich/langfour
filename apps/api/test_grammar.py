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

import grammar
from grammar import ChapterUpdate, GrammarResult, Progress

USER = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)

ES = grammar.load_curriculum("es")
SER = ES.concept["es.ser.characteristics"]                   # medium: 14 days
HARD = ES.concept["es.ser_estar_1.characteristic_vs_state"]  # hard: 7 days
RECEPTIVE = ES.concept["es.objeto_doblado.leismo"]


class FakeStore:
    def __init__(self, chapters=(), concepts=(), default_language="es"):
        self.chapter_rows = list(chapters)
        self.concept_rows = list(concepts)
        self.default = default_language
        self.recorded = None

    def default_language(self, user_id):
        return self.default

    def chapters(self, user_id):
        return self.chapter_rows

    def concepts(self, user_id):
        return self.concept_rows

    def record(self, user_id, events, concepts, chapters):
        self.recorded = (user_id, events, concepts, chapters)
        return len(events)


def practised(concept):
    """Progress after one correct use at NOW."""
    return grammar.practise(Progress(), concept, "produced", True, NOW)


# ---------------------------------------------------------------------------
# The curriculum files
# ---------------------------------------------------------------------------

def test_the_spanish_curriculum_loads_in_level_order():
    levels = [ch.level for ch in ES.chapters]
    assert levels == sorted(levels, key=grammar.LEVELS.index)
    assert ES.chapters[0].id == "es.pronombres_sujeto"
    assert len(ES.concept) > 400


def test_a_broken_curriculum_lists_every_problem():
    levels = {"a1": {"chapters": [
        {"id": "es.one", "title": "One", "goal": "g", "concepts": [
            {"id": "a", "title": "A", "scope": "s", "later": ["es.nowhere.x"]},
            {"id": "a", "title": "A again", "scope": "s", "difficulty": "brutal"},
        ]},
        {"id": "es.two", "title": "Two", "goal": "g", "continues": "es.three", "concepts": [
            {"id": "b", "title": "B", "scope": "s", "later": ["es.one.a"]},
        ]},
    ]}}
    with pytest.raises(ValueError) as err:
        grammar.parse_curriculum("es", levels)
    message = str(err.value)
    for problem in ("refers to unknown concept es.nowhere.x", "duplicate concept",
                    "difficulty is easy", "later points back to es.one.a",
                    "continues es.three"):
        assert problem in message


# ---------------------------------------------------------------------------
# The refresh rule
# ---------------------------------------------------------------------------

def test_first_correct_use_sets_the_base_interval():
    p = grammar.practise(Progress(), HARD, "produced", True, NOW)
    assert (p.interval_days, p.refresh_at, p.produced_count) == (7, NOW + 7 * DAY, 1)
    assert grammar.state(p, "started", NOW) == "fresh"
    assert grammar.state(p, "started", NOW + 8 * DAY) == "fading"


def test_using_a_rule_again_the_same_day_doesnt_grow_the_interval():
    p = practised(SER)
    for _ in range(5):
        p = grammar.practise(p, SER, "produced", True, NOW + timedelta(hours=1))
    assert p.interval_days == 14
    assert p.produced_count == 6


def test_the_interval_doubles_once_half_has_passed_and_stops_at_180():
    p = practised(SER)
    p = grammar.practise(p, SER, "produced", True, NOW + 7 * DAY)
    assert (p.interval_days, p.refresh_at) == (28, NOW + 35 * DAY)
    p = Progress(first_correct_at=NOW, interval_days=150, interval_grown_at=NOW,
                 refresh_at=NOW + 150 * DAY)
    p = grammar.practise(p, SER, "produced", True, NOW + 100 * DAY)
    assert p.interval_days == 180


def test_a_wrong_use_halves_the_interval_and_brings_it_back_tomorrow():
    p = grammar.practise(practised(SER), SER, "produced", False, NOW + 2 * DAY)
    assert (p.interval_days, p.refresh_at, p.error_count) == (7, NOW + 3 * DAY, 1)


def test_a_wrong_first_use_leaves_the_concept_studied():
    p = grammar.practise(Progress(), SER, "produced", False, NOW)
    assert p.first_correct_at is None and p.error_count == 1
    assert grammar.state(p, "started", NOW) == "studied"


def test_seeing_a_fading_concept_pushes_it_out_by_half_the_interval():
    fading = NOW + 20 * DAY
    p = grammar.practise(practised(SER), SER, "seen", None, fading)
    assert p.refresh_at == fading + 7 * DAY
    assert p.interval_days == 14
    fresh = grammar.practise(practised(SER), SER, "seen", None, NOW + DAY)
    assert fresh.refresh_at == NOW + 14 * DAY


def test_seeing_a_receptive_concept_counts_as_practice():
    p = grammar.practise(Progress(), RECEPTIVE, "seen", None, NOW)
    assert p.first_correct_at == NOW
    assert p.refresh_at == NOW + 30 * DAY  # easy


def test_progress_survives_a_round_trip_through_a_row():
    p = practised(SER)
    assert Progress.from_row(p.to_row()) == p


# ---------------------------------------------------------------------------
# Overview and details
# ---------------------------------------------------------------------------

def row(concept_id, refresh_at, interval=14):
    return {"concept_id": concept_id, "first_correct_at": (NOW - 30 * DAY).isoformat(),
            "interval_days": interval, "interval_grown_at": (NOW - 30 * DAY).isoformat(),
            "refresh_at": refresh_at.isoformat(), "produced_count": 1, "error_count": 0}


def test_the_overview_has_one_line_per_chapter_with_progress():
    store = FakeStore(
        chapters=[{"chapter_id": "es.pronombres_sujeto", "status": "done",
                   "started_at": NOW.isoformat(), "finished_at": NOW.isoformat()},
                  {"chapter_id": "es.ser", "status": "started",
                   "started_at": NOW.isoformat(), "finished_at": None}],
        concepts=[row("es.ser.identity", NOW + DAY), row("es.ser.origin", NOW - DAY),
                  row("es.gone.concept", NOW + DAY)],  # retired: ignored
    )
    out = grammar.get_overview(store, USER, None, NOW)
    lines = out.overview.splitlines()
    assert out.language == "es"
    assert "Started: es.ser. Done: 1. Fading concepts: 1." in lines[0]
    assert "✓ es.pronombres_sujeto  Pronombres personales y tratamiento  0/3 practised" in lines
    assert "→ es.ser  Ser  2/6 practised, 1 fading" in lines
    assert "· es.presente_regular  Presente: verbos regulares" in lines
    assert sum(line.startswith(("✓", "→", "·")) for line in lines) == len(ES.chapters)
    assert "teach" in out.guide


def test_the_overview_says_when_a_language_has_no_curriculum():
    out = grammar.get_overview(FakeStore(), USER, "de", NOW)
    assert "no grammar curriculum for German" in out.overview
    assert out.guide == ""


def test_details_list_a_chapter_or_concepts_in_full():
    store = FakeStore(chapters=[{"chapter_id": "es.ser_estar_1", "status": "started",
                                 "started_at": NOW.isoformat(), "finished_at": None}],
                      concepts=[row(HARD.id, NOW + DAY, 7)])
    out = grammar.get_details(store, USER, "es", ["es.ser_estar_1", "es.nope"],
                              [HARD.id, "es.ser.nope"], NOW)
    [chapter] = out.chapters
    assert chapter.status == "started"
    states = {c.id: c.state for c in chapter.concepts}
    assert states[HARD.id] == "fresh"
    assert states["es.ser_estar_1.nouns_ser"] == "studied"
    [concept] = out.concepts
    assert concept.difficulty == "hard"
    assert [r.id for r in concept.later] == list(HARD.later)
    assert concept.later[0].title
    assert out.not_found == ["es.nope", "es.ser.nope"]


def test_details_take_at_most_three_chapters():
    ids = [ch.id for ch in ES.chapters[:5]]
    out = grammar.get_details(FakeStore(), USER, "es", ids, [], NOW)
    assert len(out.chapters) == grammar.MAX_DETAIL_CHAPTERS


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def test_record_writes_events_progress_and_opens_the_chapter():
    store = FakeStore()
    out = grammar.record(store, USER, "es", [
        GrammarResult(concept=HARD.id, kind="produced", correct=True, sentence="Está cansado."),
        GrammarResult(concept="es.ser.identity", kind="seen"),
        GrammarResult(concept="es.ser.nope", kind="seen"),
    ], [ChapterUpdate(chapter="es.ser", status="started"),
        ChapterUpdate(chapter="es.nope", status="done")], NOW)

    user, events, concepts, chapters = store.recorded
    assert user == USER
    assert [e["concept_id"] for e in events] == [HARD.id, "es.ser.identity"]
    assert events[0]["sentence"] == "Está cansado."
    by_id = {c["concept_id"]: c for c in concepts}
    assert by_id[HARD.id]["refresh_at"] == (NOW + 7 * DAY).isoformat()
    assert by_id["es.ser.identity"]["first_correct_at"] is None
    assert {c["chapter_id"]: c["status"] for c in chapters} == {
        "es.ser": "started", "es.ser_estar_1": "started"}
    assert out.recorded == 2
    assert {(c.concept, c.before, c.after) for c in out.changed} == {
        (HARD.id, "not yet", "fresh"), ("es.ser.identity", "not yet", "studied")}
    assert sorted(out.chapters) == ["es.ser", "es.ser_estar_1"]
    assert out.not_found == ["es.nope", "es.ser.nope"]


def test_finishing_a_chapter_keeps_when_it_was_started_and_never_reopens():
    started = (NOW - 10 * DAY).isoformat()
    store = FakeStore(chapters=[{"chapter_id": "es.ser", "status": "started",
                                 "started_at": started, "finished_at": None}])
    grammar.record(store, USER, "es", [], [ChapterUpdate(chapter="es.ser", status="done")], NOW)
    [chapter] = store.recorded[3]
    assert (chapter["status"], chapter["started_at"]) == ("done", started)

    done = FakeStore(chapters=[chapter])
    out = grammar.record(done, USER, "es", [], [ChapterUpdate(chapter="es.ser", status="started")], NOW)
    assert done.recorded is None and out.chapters == []


def test_produced_needs_correct_and_seen_must_not_have_it():
    with pytest.raises(ValidationError):
        GrammarResult(concept=HARD.id, kind="produced")
    with pytest.raises(ValidationError):
        GrammarResult(concept=HARD.id, kind="seen", correct=True)


def test_record_refuses_a_language_without_a_curriculum():
    with pytest.raises(ValueError, match="no grammar curriculum"):
        grammar.record(FakeStore(), USER, "fr", [], [], NOW)
