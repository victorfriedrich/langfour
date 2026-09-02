import sqlite3
import zipfile
from io import BytesIO
import os

# database.py constructs the client at import time but these unit tests never
# make a network request.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DEEPINFRA_API_KEY", "test-key")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)

from flashcards import clean_anki_field, extract_from_apkg


def _make_apkg(notes):
    database = BytesIO()
    # sqlite needs a filesystem path, while the final deck remains in memory.
    import tempfile

    with tempfile.NamedTemporaryFile() as db_file:
        connection = sqlite3.connect(db_file.name)
        connection.execute("CREATE TABLE notes (flds TEXT)")
        connection.executemany("INSERT INTO notes VALUES (?)", [(note,) for note in notes])
        connection.commit()
        connection.close()
        database.write(open(db_file.name, "rb").read())

    deck = BytesIO()
    with zipfile.ZipFile(deck, "w") as archive:
        archive.writestr("collection.anki2", database.getvalue())
    return deck.getvalue()


def test_clean_anki_field_strips_html_and_media_markup():
    value = "<div><b>llevar</b>&nbsp;<i>algo</i><br>[sound:word.mp3]</div>"

    assert clean_anki_field(value) == "llevar algo"


def test_clean_anki_field_uses_remnote_breadcrumb_leaf():
    value = "<ul><li>Spanisch<ul><li>Lektion 8<ul><li><b>llevar</b></li></ul></li></ul></li></ul>"

    assert clean_anki_field(value) == "llevar"


def test_extract_apkg_imports_each_note_once_and_cleans_both_fields():
    deck = _make_apkg(
        [
            (
                "<ul><li>Spanisch<ul><li>Lektion 8<ul><li>llevar</li></ul></li></ul></li></ul>"
                "\x1f<div>mitbringen</div>"
            )
        ]
    )

    assert extract_from_apkg(deck) == [{"word": "llevar", "translation": "mitbringen"}]


def test_extract_apkg_splits_remnote_pair_stored_in_one_field():
    deck = _make_apkg(
        [
            "<div>existir, haber&nbsp; :: &nbsp;existieren, bestehen</div>\x1fmetadata",
            "tomar forma :: Form annehmen\x1f",
        ]
    )

    assert extract_from_apkg(deck) == [
        {"word": "existir, haber", "translation": "existieren, bestehen"},
        {"word": "tomar forma", "translation": "Form annehmen"},
    ]


def test_extract_apkg_does_not_split_colons_inside_vocabulary():
    deck = _make_apkg(["la hora: 10:30\x1fdie Uhrzeit"])

    assert extract_from_apkg(deck) == [
        {"word": "la hora: 10:30", "translation": "die Uhrzeit"}
    ]
