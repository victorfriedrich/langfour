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
UV = ES.concept["es.indefinido_irregular.uv"]                # forms for tener, estar, andar


class FakeStore:
    def __init__(self, chapters=(), concepts=(), default_language="es", events=()):
        self.chapter_rows = list(chapters)
        self.concept_rows = list(concepts)
        self.event_rows = list(events)
        self.default = default_language
        self.recorded = None

    def default_language(self, user_id):
        return self.default

    def chapters(self, user_id):
        return self.chapter_rows

    def concepts(self, user_id):
        return self.concept_rows

    def events(self, user_id, since):
        return [e for e in self.event_rows if datetime.fromisoformat(e["occurred_at"]) >= since]

    def topic_events(self, user_id, language):
        return sorted((e for e in self.event_rows if e.get("topic")),
                      key=lambda e: e["occurred_at"], reverse=True)

    def record(self, user_id, events, concepts, chapters):
        self.recorded = (user_id, events, concepts, chapters)
        return len(events)


def learned(concept, at=NOW):
    """Progress once a concept meets the bar at `at`, using every form it lists."""
    if concept.mode == "receptive":
        return grammar.practise(Progress(), concept, "seen", None, at)
    p, forms = Progress(), {f for _, fs in concept.forms for f in fs}
    for _ in range(grammar.MIN_CORRECT):
        p = grammar.practise(p, concept, "produced", True, at, forms)
    assert p.learned_at == at
    return p


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
            {"id": "a", "title": "A again", "scope": "s", "difficulty": "brutal",
             "forms": ["tuve", "tuvo"]},
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
                    "continues es.three", "forms maps each verb"):
        assert problem in message


# ---------------------------------------------------------------------------
# The refresh rule
# ---------------------------------------------------------------------------

def test_one_correct_sentence_isnt_enough_and_learning_sets_the_base_interval():
    p = grammar.practise(Progress(), HARD, "produced", True, NOW)
    assert grammar.state(p, "started", NOW) == "studied"
    assert (p.first_correct_at, p.correct_count, p.refresh_at) == (NOW, 1, None)
    assert grammar.to_learn(p, HARD) == "1 more correct sentence written by the user."
    p = grammar.practise(p, HARD, "produced", True, NOW + DAY)
    assert (p.learned_at, p.interval_days, p.refresh_at) == (NOW + DAY, 7, NOW + 8 * DAY)
    assert grammar.state(p, "started", NOW + DAY) == "fresh"
    assert grammar.state(p, "started", NOW + 9 * DAY) == "fading"
    assert grammar.to_learn(p, HARD) is None


def test_a_concept_with_forms_needs_half_of_each_verbs_forms():
    p = Progress()
    for sentence in ("Ayer tuve un problema.", "Ella tuvo suerte.", "Estuve en casa."):
        p = grammar.practise(p, UV, "produced", True, NOW, grammar.forms_in(sentence, UV))
    assert p.learned_at is None and p.correct_count == 3
    assert p.forms_produced == ("estuve", "tuve", "tuvo")
    left = grammar.to_learn(p, UV)
    assert "tener: 1 more of tuviste, tuvimos, tuvieron" in left
    assert "estar: 2 more" in left and "andar: 2 more of anduve, anduvo, anduvieron" in left
    assert "sentence" not in left
    for sentence in ("Tuvimos tiempo y estuvimos bien.", "Estuvieron allí.",
                     "Anduve mucho y él anduvo poco."):
        p = grammar.practise(p, UV, "produced", True, NOW, grammar.forms_in(sentence, UV))
    assert p.learned_at == NOW


def test_wrong_sentences_dont_count_toward_the_bar():
    p = grammar.practise(Progress(), UV, "produced", False, NOW, {"tuve"})
    assert (p.correct_count, p.forms_produced, p.error_count) == (0, (), 1)


def test_recognizing_a_form_isnt_using_it():
    p = Progress()
    for _ in range(5):
        p = grammar.practise(p, SER, "recognized", True, NOW)
    assert p == Progress()


def test_a_self_report_learns_the_concept_at_once():
    p = grammar.practise(Progress(), UV, "produced", True, NOW, self_reported=True)
    assert p.learned_at == NOW and p.correct_count == 0


def test_forms_match_whole_words_with_their_accents():
    tu = ES.concept["es.imperativo_1.tu_irregular"]
    assert grammar.forms_in("¡Hazlo ya y dímelo! Ve a casa.", tu) == {"haz", "di", "ve"}
    ser = ES.concept["es.ser.forms"]
    assert grammar.forms_in("Este es mi hermano; somos dos.", ser) == {"es", "somos"}
    assert grammar.forms_in("Ayer tuvé un problema.", UV) == set()


def test_using_a_rule_again_the_same_day_doesnt_grow_the_interval():
    p = learned(SER)
    for _ in range(5):
        p = grammar.practise(p, SER, "produced", True, NOW + timedelta(hours=1))
    assert p.interval_days == 14
    assert p.produced_count == 7
    assert p.refresh_at == NOW + 14 * DAY


def test_the_interval_doubles_once_half_has_passed_and_stops_at_180():
    p = learned(SER)
    p = grammar.practise(p, SER, "produced", True, NOW + 7 * DAY)
    assert (p.interval_days, p.refresh_at) == (28, NOW + 35 * DAY)
    p = Progress(first_correct_at=NOW, learned_at=NOW, interval_days=150, interval_grown_at=NOW,
                 refresh_at=NOW + 150 * DAY)
    p = grammar.practise(p, SER, "produced", True, NOW + 100 * DAY)
    assert p.interval_days == 180


def test_a_wrong_use_halves_the_interval_and_brings_it_back_tomorrow():
    p = grammar.practise(learned(SER), SER, "produced", False, NOW + 2 * DAY)
    assert (p.interval_days, p.refresh_at, p.error_count) == (7, NOW + 3 * DAY, 1)


def test_a_wrong_first_use_leaves_the_concept_studied():
    p = grammar.practise(Progress(), SER, "produced", False, NOW)
    assert p.learned_at is None and p.error_count == 1
    assert grammar.state(p, "started", NOW) == "studied"


def test_seeing_a_fading_concept_pushes_it_out_by_half_the_interval():
    fading = NOW + 20 * DAY
    p = grammar.practise(learned(SER), SER, "seen", None, fading)
    assert p.refresh_at == fading + 7 * DAY
    assert p.interval_days == 14
    fresh = grammar.practise(learned(SER), SER, "seen", None, NOW + DAY)
    assert fresh.refresh_at == NOW + 14 * DAY


def test_seeing_a_receptive_concept_counts_as_practice():
    p = grammar.practise(Progress(), RECEPTIVE, "seen", None, NOW)
    assert p.learned_at == NOW
    assert p.refresh_at == NOW + 30 * DAY  # easy


def test_progress_survives_a_round_trip_through_a_row():
    p = grammar.practise(learned(SER), UV, "produced", True, NOW, {"tuve"})
    assert Progress.from_row(p.to_row()) == p


# ---------------------------------------------------------------------------
# Overview and details
# ---------------------------------------------------------------------------

def row(concept_id, refresh_at, interval=14):
    return {"concept_id": concept_id, "first_correct_at": (NOW - 30 * DAY).isoformat(),
            "learned_at": (NOW - 30 * DAY).isoformat(), "correct_count": 2,
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
    assert "✓ es.pronombres_sujeto  Pronombres personales y tratamiento  0/3 learned" in lines
    assert "→ es.ser  Ser  2/6 learned, 1 fading" in lines
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
    to_learn = {c.id: c.to_learn for c in chapter.concepts}
    assert to_learn[HARD.id] is None
    assert to_learn["es.ser_estar_1.nouns_ser"] == "2 more correct sentences written by the user."
    [concept] = out.concepts
    assert concept.difficulty == "hard"
    assert [r.id for r in concept.later] == list(HARD.later)
    assert concept.later[0].title
    assert out.not_found == ["es.nope", "es.ser.nope"]


def test_details_show_which_forms_are_left():
    p = grammar.practise(Progress(), UV, "produced", True, NOW, {"tuve"})
    store = FakeStore(chapters=[{"chapter_id": UV.chapter_id, "status": "started",
                                 "started_at": NOW.isoformat(), "finished_at": None}],
                      concepts=[{"concept_id": UV.id, **p.to_row()}])
    [concept] = grammar.get_details(store, USER, "es", [], [UV.id], NOW).concepts
    assert concept.state == "studied" and concept.refresh_at is None
    assert concept.forms["andar"] == ["anduve", "anduvo", "anduvieron"]
    assert (concept.forms_produced, concept.correct_sentences) == (["tuve"], 1)
    assert "tener: 2 more of tuviste" in concept.to_learn


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
    assert {e["concept_id"] for e in events} == {HARD.id, "es.ser.identity"}
    assert next(e for e in events if e["concept_id"] == HARD.id)["sentence"] == "Está cansado."
    by_id = {c["concept_id"]: c for c in concepts}
    assert by_id[HARD.id]["correct_count"] == 1 and by_id[HARD.id]["learned_at"] is None
    assert by_id["es.ser.identity"]["first_correct_at"] is None
    assert {c["chapter_id"]: c["status"] for c in chapters} == {
        "es.ser": "started", "es.ser_estar_1": "started"}
    assert out.recorded == 2
    assert {(c.concept, c.before, c.after) for c in out.changed} == {
        (HARD.id, "not yet", "studied"), ("es.ser.identity", "not yet", "studied")}
    assert out.to_learn[HARD.id] == "1 more correct sentence written by the user."
    assert sorted(out.chapters) == ["es.ser", "es.ser_estar_1"]
    assert out.not_found == ["es.nope", "es.ser.nope"]


def test_finishing_a_chapter_keeps_when_it_was_started_and_never_reopens():
    started = (NOW - 10 * DAY).isoformat()
    store = FakeStore(chapters=[{"chapter_id": "es.ser", "status": "started",
                                 "started_at": started, "finished_at": None}])
    grammar.record(store, USER, "es", [], [ChapterUpdate(chapter="es.ser", status="done",
                                                         self_reported=True)], NOW)
    [chapter] = store.recorded[3]
    assert (chapter["status"], chapter["started_at"]) == ("done", started)

    done = FakeStore(chapters=[chapter])
    out = grammar.record(done, USER, "es", [], [ChapterUpdate(chapter="es.ser", status="started")], NOW)
    assert done.recorded is None and out.chapters == []


def test_a_chapter_is_done_only_once_its_concepts_are_learned():
    chapter = ES.chapter["es.indefinido_irregular"]
    started = {"chapter_id": chapter.id, "status": "started",
               "started_at": NOW.isoformat(), "finished_at": None}
    almost = [{"concept_id": c.id, **learned(c).to_row()}
              for c in chapter.concepts[:-1]]
    store = FakeStore(chapters=[started], concepts=almost)
    out = grammar.record(store, USER, "es", [], [ChapterUpdate(chapter=chapter.id, status="done")], NOW)
    assert out.not_done == [chapter.id] and out.chapters == [] and store.recorded is None

    last = chapter.concepts[-1]
    out = grammar.record(store, USER, "es", [
        GrammarResult(concept=last.id, kind="produced", correct=True, sentence=s)
        for s in ("Hubo un accidente.", "Ayer hubo una fiesta.")
    ], [ChapterUpdate(chapter=chapter.id, status="done")], NOW)
    assert out.not_done == [] and out.chapters == [chapter.id]
    assert store.recorded[3][0]["status"] == "done"


def test_the_same_sentence_twice_counts_once():
    store = FakeStore()
    out = grammar.record(store, USER, "es", [
        GrammarResult(concept=SER.id, kind="produced", correct=True, sentence=s)
        for s in ("Es alto.", "es  alto.")
    ], [], NOW)
    assert out.recorded == 1 and store.recorded[2][0]["correct_count"] == 1


def test_produced_needs_correct_and_a_sentence_and_seen_must_not_have_correct():
    with pytest.raises(ValidationError):
        GrammarResult(concept=HARD.id, kind="produced")
    with pytest.raises(ValidationError):
        GrammarResult(concept=HARD.id, kind="produced", correct=True)
    with pytest.raises(ValidationError):
        GrammarResult(concept=HARD.id, kind="seen", correct=True)
    with pytest.raises(ValidationError):
        GrammarResult(concept=HARD.id, kind="recognized")
    with pytest.raises(ValidationError):
        GrammarResult(concept=HARD.id, kind="recognized", correct=True, self_reported=True)
    GrammarResult(concept=HARD.id, kind="produced", correct=True, self_reported=True)


def test_record_refuses_a_language_without_a_curriculum():
    with pytest.raises(ValueError, match="no grammar curriculum"):
        grammar.record(FakeStore(), USER, "fr", [], [], NOW)


@pytest.mark.parametrize("kind,correct", [("produced", True), ("seen", None)])
def test_early_practice_keeps_tomorrows_refresh_after_an_error(kind, correct):
    p = grammar.practise(learned(RECEPTIVE), RECEPTIVE, "produced", False, NOW + DAY)
    after = grammar.practise(p, RECEPTIVE, kind, correct, NOW + DAY + timedelta(hours=1))
    assert after.refresh_at == p.refresh_at == NOW + 2 * DAY
    assert after.interval_days == p.interval_days
    assert after.interval_grown_at == p.interval_grown_at


@pytest.mark.parametrize("previous", [None, learned(RECEPTIVE)])
def test_receptive_exposure_doesnt_override_a_sessions_error_in_either_order(previous):
    seen = GrammarResult(concept=RECEPTIVE.id, kind="seen")
    wrong = GrammarResult(concept=RECEPTIVE.id, kind="produced", correct=False,
                          sentence="Le vi ayer.")
    saved = []
    for results in ([seen, wrong], [wrong, seen]):
        store = FakeStore(concepts=[{"concept_id": RECEPTIVE.id, **previous.to_row()}]
                          if previous else [])
        grammar.record(store, USER, "es", results, [], NOW + DAY)
        [progress] = store.recorded[2]
        assert progress["refresh_at"] == (NOW + 2 * DAY).isoformat()
        assert progress["error_count"] == 1
        assert progress["last_seen_at"] == (NOW + DAY).isoformat()
        saved.append(progress)
    assert saved[0] == saved[1]


def test_record_rereads_after_a_conflict_and_preserves_the_other_sessions_progress():
    class OverlappingStore(FakeStore):
        calls = 0

        def record(self, user_id, events, concepts, chapters):
            self.calls += 1
            if self.calls == 1:
                assert concepts[0]["previous"] is None
                assert chapters[0]["previous"] is None
                # Another request produced the concept and finished its chapter
                # between our read and our attempted write. The RPC wrote nothing.
                self.concept_rows = [{"concept_id": SER.id, **learned(SER).to_row()}]
                self.chapter_rows = [{"chapter_id": SER.chapter_id, "status": "done",
                                      "started_at": NOW.isoformat(),
                                      "finished_at": NOW.isoformat()}]
                return -1
            return super().record(user_id, events, concepts, chapters)

    store = OverlappingStore()
    out = grammar.record(store, USER, "es", [GrammarResult(concept=SER.id, kind="seen")],
                         [ChapterUpdate(chapter=SER.chapter_id, status="started")], NOW + DAY)
    assert store.calls == 2
    assert out.recorded == 1 and out.chapters == [] and out.changed == []
    _, events, [progress], chapters = store.recorded
    assert len(events) == 1 and chapters == []
    assert progress["learned_at"] == NOW.isoformat()
    assert progress["produced_count"] == 2
    assert progress["refresh_at"] == (NOW + 14 * DAY).isoformat()
    assert progress["previous"] == store.concept_rows[0]


def test_record_stops_after_three_conflicts():
    class ConflictingStore(FakeStore):
        calls = 0

        def record(self, *args):
            self.calls += 1
            return -1

    store = ConflictingStore()
    with pytest.raises(RuntimeError, match="please try again"):
        grammar.record(store, USER, "es", [GrammarResult(concept=SER.id, kind="seen")], [], NOW)
    assert store.calls == 3


# ---------------------------------------------------------------------------
# The web app's grammar book
# ---------------------------------------------------------------------------

def test_the_book_numbers_every_chapter_and_gives_each_concept_its_state():
    store = FakeStore(chapters=[{"chapter_id": "es.ser", "status": "started",
                                 "started_at": NOW.isoformat(), "finished_at": None}],
                      concepts=[row("es.ser.identity", NOW + DAY), row("es.ser.origin", NOW - DAY)])
    book = grammar.get_book(store, USER, "es", NOW)
    assert [c.number for c in book.chapters] == list(range(1, len(ES.chapters) + 1))
    ser = next(c for c in book.chapters if c.id == "es.ser")
    states = {c.id: c.state for c in ser.concepts}
    assert (ser.status, states["es.ser.identity"], states["es.ser.origin"],
            states["es.ser.forms"]) == ("started", "fresh", "fading", "studied")
    assert grammar.get_book(store, USER, "de", NOW).chapters == []


def test_a_lesson_has_its_concepts_in_full_and_its_neighbours():
    store = FakeStore(concepts=[row("es.ser.identity", NOW + DAY)])
    lesson = grammar.get_lesson(store, USER, "es", "es.ser", NOW)
    assert (lesson.number, lesson.status) == (2, "not started")
    assert (lesson.previous.id, lesson.next.id) == ("es.pronombres_sujeto", "es.presente_regular")
    identity = next(c for c in lesson.concepts if c.id == "es.ser.identity")
    assert (identity.state, identity.used) == ("fresh", 1)
    assert identity.see[0].chapter.id == "es.ser_estar_1"
    with pytest.raises(LookupError):
        grammar.get_lesson(store, USER, "es", "es.nope", NOW)


def test_a_concept_can_carry_an_image():
    level = {"chapters": [{"id": "xx.a", "title": "A", "goal": "g", "concepts": [
        {"id": "c", "title": "C", "scope": "s", "image": "a-c.webp"}]}]}
    assert grammar.parse_curriculum("xx", {"a1": level}).concept["xx.a.c"].image == "a-c.webp"


def test_the_ui_copy_covers_every_chapter_and_concept():
    copy = grammar.load_ui_copy("es")  # raises on a missing or extra id
    assert len(copy) == len(ES.chapters) + len(ES.concept)
    assert all(c.title and c.description for c in copy.values())


def test_the_book_and_lessons_use_the_ui_copy():
    copy = grammar.load_ui_copy("es")
    ser = next(c for c in grammar.get_book(FakeStore(), USER, "es", NOW).chapters if c.id == "es.ser")
    assert (ser.title, ser.description) == (copy["es.ser"].title, copy["es.ser"].description)
    lesson = grammar.get_lesson(FakeStore(), USER, "es", "es.ser", NOW)
    assert lesson.concepts[0].description == copy["es.ser.forms"].description
    assert lesson.concepts[1].see[0].title == copy[lesson.concepts[1].see[0].id].title


# ---------------------------------------------------------------------------
# Mistakes to revise
# ---------------------------------------------------------------------------

LO = ES.concept["es.objeto_directo.forms"]


def test_a_mistake_is_flagged_with_its_note_until_the_next_correct_use():
    p = grammar.practise(Progress(), LO, "produced", False, NOW, note="lo for la factura")
    assert (p.mistake_at, p.mistake) == (NOW, "2026-10-29: lo for la factura")
    p = grammar.practise(p, LO, "recognized", True, NOW + DAY)
    assert p.mistake_at == NOW  # choosing right isn't using it
    p = grammar.practise(p, LO, "produced", True, NOW + DAY)
    assert (p.mistake_at, p.mistake_note) == (None, None)
    wrong_choice = grammar.practise(Progress(), LO, "recognized", False, NOW, note="lo for la")
    assert wrong_choice.mistake_note == "lo for la"


def test_a_mistake_in_an_unreached_chapter_is_kept_without_starting_it():
    store = FakeStore()
    out = grammar.record(store, USER, "es", [
        GrammarResult(concept=LO.id, kind="produced", correct=False,
                      sentence="Los clientes pidieron una factura y lo busqué.",
                      note="lo for la factura: the pronoun agrees with the feminine noun"),
    ], [], NOW)
    _, [event], [progress], chapters = store.recorded
    assert chapters == [] and out.changed == []
    assert event["note"].startswith("lo for la factura")
    assert progress["mistake_note"].startswith("lo for la factura")
    assert progress["mistake_at"] == NOW.isoformat()


def test_the_overview_lists_mistakes_to_revise_newest_first():
    old = grammar.practise(Progress(), SER, "produced", False, NOW - DAY, note="es for está")
    new = grammar.practise(Progress(), LO, "produced", False, NOW, note="lo for la")
    store = FakeStore(chapters=[{"chapter_id": SER.chapter_id, "status": "started",
                                 "started_at": NOW.isoformat(), "finished_at": None}],
                      concepts=[{"concept_id": SER.id, **old.to_row()},
                                {"concept_id": LO.id, **new.to_row()}])
    lines = grammar.get_overview(store, USER, "es", NOW).overview.splitlines()
    assert "Mistakes to revise: 2." in lines[0]
    at = lines.index(next(line for line in lines if line.startswith("TO REVISE")))
    assert lines[at + 1] == f"{LO.id}  2026-10-29: lo for la  (chapter not started)"
    assert lines[at + 2] == f"{SER.id}  2026-10-28: es for está"
    [concept] = grammar.get_details(store, USER, "es", [], [LO.id], NOW).concepts
    assert concept.mistake == "2026-10-29: lo for la"


def test_a_note_is_for_wrong_results_only():
    with pytest.raises(ValidationError):
        GrammarResult(concept=LO.id, kind="produced", correct=True, sentence="La busqué.",
                      note="fine")


# ---------------------------------------------------------------------------
# Chapters worth revisiting
# ---------------------------------------------------------------------------

STARTED_PRETERITE = {"es.indefinido_irregular": {"status": "started"}}  # chapter 30, A2


def used(concept_id, days_ago, correct=True, kind="produced", self_reported=False):
    return {"concept_id": concept_id, "kind": kind, "correct": correct,
            "self_reported": self_reported, "occurred_at": (NOW - days_ago * DAY).isoformat()}


def slipping(concept_id):
    """Used on four days, wrong on two of them."""
    return [used(concept_id, 9, False), used(concept_id, 6), used(concept_id, 4, False),
            used(concept_id, 4), used(concept_id, 1)]


def worth(events, chapters=STARTED_PRETERITE, progress=None):
    """The chapter ids worth revisiting."""
    return [w.chapter for w in
            grammar.worth_revisiting(ES, chapters, progress or {}, events, NOW)]


def test_a_chapter_used_often_and_slipping_on_several_days_is_worth_revisiting():
    assert worth(slipping(UV.id)) == ["es.indefinido_irregular"]


def test_slips_on_a_single_day_are_just_learning_it():
    events = [used(UV.id, 1, False), used(UV.id, 1, False, "recognized"),
              used(UV.id, 5), used(UV.id, 8)]
    assert worth(events) == []


def test_a_chapter_used_on_too_few_days_is_left_alone():
    assert worth([used(UV.id, 9, False), used(UV.id, 4, False)]) == []


def test_only_chapters_near_the_users_level_count():
    a1 = "es.presente_regular.ir"                             # one level below: counts
    b2 = "es.pasiva.ser_participle"                           # far ahead
    later_a2 = ES.chapter["es.indefinidos"].concepts[0].id    # same level, 9 chapters on
    assert worth(slipping(a1) + slipping(b2) + slipping(later_a2)) == ["es.presente_regular"]
    assert worth(slipping(UV.id), chapters={}) == []          # nothing reached yet


def test_a_learned_concept_counts_as_reaching_its_chapter():
    progress = {UV.id: learned(UV, NOW - 20 * DAY)}
    assert worth(slipping(UV.id), chapters={}, progress=progress) == ["es.indefinido_irregular"]


def test_correct_use_on_later_days_settles_it():
    events = [*slipping(UV.id), used(UV.id, 0)]
    assert worth(events) == []  # correct on days 1 and 0 after the last slip on day 4


def test_old_events_and_self_reports_dont_count():
    old = [used(UV.id, 40, False), used(UV.id, 35, False), used(UV.id, 33)]
    assert worth(old) == []
    reported = [used(UV.id, d, self_reported=True) for d in (2, 3, 5)]
    assert worth([used(UV.id, 9, False), used(UV.id, 4, False), *reported]) == []


def test_at_most_two_chapters_with_the_most_slip_days_first():
    imperfecto = ES.chapter["es.imperfecto"].concepts[0].id
    a1 = "es.presente_regular.ir"
    more = [*slipping(imperfecto), used(imperfecto, 2, False)]
    assert worth(slipping(UV.id) + slipping(a1) + more)[0] == "es.imperfecto"
    assert len(worth(slipping(UV.id) + slipping(a1) + more)) == grammar.WORTH_MAX


def test_the_rules_that_slip_often_come_with_their_chapter():
    ser_ir = "es.indefinido_irregular.ser_ir"
    events = [*slipping(UV.id), used(ser_ir, 7, False), used(ser_ir, 5)]
    [w] = grammar.worth_revisiting(ES, STARTED_PRETERITE, {}, events, NOW)
    assert w.concepts == [UV.id]  # ser/ir slipped once, so it isn't marked
    events += [used(UV.id, 0)]    # wrong on day 4, right on days 1 and 0: settled
    events += [used(ser_ir, 1, False), used(ser_ir, 0, False)]
    [w] = grammar.worth_revisiting(ES, STARTED_PRETERITE, {}, events, NOW)
    assert w.concepts == [ser_ir]


def test_a_lesson_marks_the_rules_worth_revisiting():
    store = FakeStore(chapters=[{"chapter_id": "es.indefinido_irregular", "status": "started",
                                 "started_at": NOW.isoformat(), "finished_at": None}],
                      events=slipping(UV.id))
    lesson = grammar.get_lesson(store, USER, "es", "es.indefinido_irregular", NOW)
    assert [c.id for c in lesson.concepts if c.revisit] == [UV.id]
    other = grammar.get_lesson(store, USER, "es", "es.imperfecto", NOW)
    assert not any(c.revisit for c in other.concepts)


def test_the_book_and_the_overview_name_the_chapters_worth_revisiting():
    store = FakeStore(chapters=[{"chapter_id": "es.indefinido_irregular", "status": "started",
                                 "started_at": NOW.isoformat(), "finished_at": None}],
                      events=slipping(UV.id))
    [w] = grammar.get_book(store, USER, "es", NOW).worth_revisiting
    assert (w.chapter, w.concepts) == ("es.indefinido_irregular", [UV.id])
    overview = grammar.get_overview(store, USER, "es", NOW).overview
    assert f"Worth revisiting: es.indefinido_irregular (slips most: {UV.id})" in overview
    assert "Worth revisiting" not in grammar.get_overview(FakeStore(), USER, "es", NOW).overview


# ---------------------------------------------------------------------------
# Several concepts on one result, and mistakes no concept covers
# ---------------------------------------------------------------------------

PRETERITE = "es.indefinido_irregular.uv"


def test_one_result_can_name_several_concepts():
    store = FakeStore()
    sentence = "El hotel tuve una azotea, pero fue vacía."
    out = grammar.record(store, USER, "es", [
        GrammarResult(concept=HARD.id, concepts=[PRETERITE, HARD.id, "es.nope"],
                      kind="produced", correct=False, sentence=sentence,
                      note="tuve for tenía; fue vacía for estaba vacía"),
    ], [], NOW)
    _, events, concepts, _ = store.recorded
    assert [e["concept_id"] for e in events] == [HARD.id, PRETERITE]
    assert {e["sentence"] for e in events} == {sentence}
    assert {c["concept_id"]: c["mistake_note"] for c in concepts} == {
        HARD.id: "tuve for tenía; fue vacía for estaba vacía",
        PRETERITE: "tuve for tenía; fue vacía for estaba vacía"}
    assert out.recorded == 2 and out.not_found == ["es.nope"]


def test_a_mistake_no_concept_covers_is_filed_under_a_topic():
    store = FakeStore()
    out = grammar.record(store, USER, "es", [
        GrammarResult(topic="  Gender of nouns in  -MA ", kind="produced", correct=False,
                      sentence="La problema es grande.", note="la problema for el problema"),
        GrammarResult(concept=SER.id, topic="gender of nouns in -ma", kind="produced",
                      correct=False, sentence="Es el tema muy difícil.", note="es for está"),
    ], [], NOW)
    _, events, concepts, chapters = store.recorded
    topic = [e for e in events if e["topic"]]
    assert [(e["concept_id"], e["topic"], e["language"]) for e in topic] == [
        (None, "gender of nouns in -ma", "es")] * 2
    assert [c["concept_id"] for c in concepts] == [SER.id] and chapters == []
    assert out.topics == ["gender of nouns in -ma"] and out.recorded == 3


def test_the_overview_lists_open_topics_and_every_topic_for_reuse():
    def event(topic, correct, at, note=None):
        return {"concept_id": None, "topic": topic, "kind": "produced", "correct": correct,
                "note": note, "occurred_at": at.isoformat()}
    store = FakeStore(events=[
        event("gender of nouns in -ma", False, NOW - 3 * DAY, "la tema"),
        event("gender of nouns in -ma", False, NOW - DAY, "la problema for el problema"),
        event("personal a", False, NOW - 2 * DAY, "veo Juan"),
        event("personal a", True, NOW),  # put right since
    ])
    lines = grammar.get_overview(store, USER, "es", NOW).overview.splitlines()
    assert "Mistakes to revise: 1." in lines[0]
    assert ("topic 'gender of nouns in -ma'  2026-10-28: la problema for el problema"
            "  (no concept, 2 mistakes)") in lines
    assert not any(line.startswith("topic 'personal a'") for line in lines)
    assert ("Topics for mistakes no concept covers (reuse one that fits): "
            "'personal a'; 'gender of nouns in -ma'") in lines


def test_a_result_needs_a_concept_or_a_topic_and_seen_takes_no_topic():
    with pytest.raises(ValidationError):
        GrammarResult(kind="produced", correct=False, sentence="La problema.")
    with pytest.raises(ValidationError):
        GrammarResult(topic="gender of nouns in -ma", kind="seen")
    with pytest.raises(ValidationError):
        GrammarResult(concepts=[SER.id] * 6, kind="seen")
