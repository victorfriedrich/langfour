"""The word cache: which root a token links to when roots share a form."""

import pytest


@pytest.fixture
def db(monkeypatch):
    # Client construction needs configuration; no request is made.
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature")
    monkeypatch.setenv("REQUIRE_SERVICE_ROLE", "0")
    import database
    return database


def test_a_shared_form_stays_with_the_older_root(db, monkeypatch):
    """'editaron' is a form of the real root 'editar' and, since a later video,
    of the English root 'edit' too. Roots load in id order, and the junk copy is
    always the newer one, so the first root must keep the form."""
    pages = [[
        {"word_id": 111691, "word": "editar", "wordform": "editaron"},
        {"word_id": 130641, "word": "edit", "wordform": "editaron"},
    ]]
    monkeypatch.setattr(db, "SUPPORTED_LANGUAGES", ["es"])
    monkeypatch.setattr(db, "fetch_paginated_records",
                        lambda language, last, limit: pages.pop(0) if pages else [])
    db.initialize_cache()
    assert db.identify_word_id("editaron", "es") == 111691


def test_a_new_root_does_not_take_over_an_existing_form(db, monkeypatch):
    monkeypatch.setattr(db, "word_cache", {"es": {"words": {}, "wordforms": {"editaron": 111691}}})
    class Insert:
        def insert(self, row):
            return self

        def update(self, row):
            return self

        def eq(self, *a):
            return self

        def execute(self):
            return None

    monkeypatch.setattr(db.supabase, "table", lambda name: Insert())
    db.add_and_flag_wordform("editaron", 130641, "es", flagged=False)
    assert db.identify_word_id("editaron", "es") == 111691
