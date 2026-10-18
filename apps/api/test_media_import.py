import pytest

from media_import import (
    MediaExistsError,
    get_media,
    get_media_words,
    import_media,
    list_media,
    make_media_id,
)


class FakeStore:
    """user_media in memory, keyed the way the table's primary key is."""

    def __init__(self):
        self.rows = {}

    def insert(self, user_id, row):
        key = (user_id, row["language"], row["id"])
        if key in self.rows:
            raise MediaExistsError(row["id"])
        self.rows[key] = {**row, "user_id": user_id}

    def exists(self, user_id, language, media_id):
        return (user_id, language, media_id) in self.rows

    def list(self, user_id, language):
        rows = [r for (u, lang, _), r in self.rows.items() if u == user_id and lang == language]
        return [{k: v for k, v in r.items() if k not in ("chunks", "words", "user_id")}
                for r in sorted(rows, key=lambda r: r["imported_at"], reverse=True)]

    def get(self, user_id, language, media_id, columns="*"):
        row = self.rows.get((user_id, language, media_id))
        if row is None:
            return None
        return row if columns == "*" else {c: row[c] for c in columns.split(",")}


ALICE, BOB = "alice", "bob"


def run(store, payload, user=ALICE, words=None):
    parsed = []

    def parser(groups, source, language):
        parsed.append(source)
        return words if words is not None else [{"content": "hola", "id": 42}]

    return import_media(store, user, payload, parser, lambda text: [text]), parsed


def episode(**over):
    return {
        "series": "La Casa Azul", "season": 1, "episode": 2, "language": "spanish",
        "model": "whisper-large-v3-turbo", "audio_seconds": 10.5,
        "chunks": [{"timestamp": [0, 2.5], "text": " Hola mundo. "}, {"timestamp": [3, 5], "text": "Hasta luego."}],
        **over,
    }


def test_import_saves_the_episode_for_its_user():
    store = FakeStore()
    result, _ = run(store, episode())

    assert result["id"] == "la-casa-azul-s01-e02"
    assert result["chunks"][0]["text"] == "Hola mundo."
    assert result["type"] == "series"
    catalog = list_media(store, ALICE, "es")
    assert catalog[0]["series"] == "La Casa Azul"
    assert "chunks" not in catalog[0]
    assert get_media(store, ALICE, result["id"], "spanish")["chunks"][1]["text"] == "Hasta luego."
    assert get_media_words(store, ALICE, result["id"], "es") == [{"content": "hola", "id": 42}]


def test_items_are_only_visible_to_their_owner():
    store = FakeStore()
    result, _ = run(store, episode())

    assert list_media(store, BOB, "es") == []
    with pytest.raises(FileNotFoundError):
        get_media(store, BOB, result["id"], "es")
    with pytest.raises(FileNotFoundError):
        get_media_words(store, BOB, result["id"], "es")
    # The same episode can be in two people's Libraries.
    run(store, episode(), user=BOB)
    assert [m["id"] for m in list_media(store, BOB, "es")] == [result["id"]]


def test_a_duplicate_is_refused_before_parsing():
    store = FakeStore()
    run(store, episode())
    calls = []
    with pytest.raises(MediaExistsError, match="already exists: la-casa-azul-s01-e02"):
        import_media(store, ALICE, episode(), lambda *args: calls.append(args) or [], lambda text: [text])
    assert calls == []


def test_import_rejects_out_of_order_chunks():
    payload = episode(chunks=[{"timestamp": [0, 3], "text": "One"}, {"timestamp": [1, 4], "text": "Two"}])
    with pytest.raises(ValueError, match="overlaps"):
        run(FakeStore(), payload)


def test_import_trims_small_whisper_overlaps():
    payload = episode(chunks=[{"timestamp": [0, 5.37], "text": "One"}, {"timestamp": [5, 6], "text": "Two"}])
    result, _ = run(FakeStore(), payload)
    assert result["chunks"][1]["timestamp"] == [5.37, 6]


def test_import_article_without_timestamps():
    store = FakeStore()
    result, _ = run(store, {
        "media_type": "article", "title": "La economía crece", "site": "El País",
        "source_url": "https://elpais.com/economia/1", "language": "es",
        "chunks": [{"timestamp": None, "text": "Primer párrafo."}, {"text": "Segundo párrafo."}],
    })
    assert result["id"].startswith("la-economia-crece-")
    assert result["type"] == "article"
    assert result["duration"] is None
    assert result["wordCount"] == 4
    assert result["sourceUrl"] == "https://elpais.com/economia/1"
    assert result["chunks"][1] == {"timestamp": None, "text": "Segundo párrafo."}


def test_import_rejects_mixed_timestamps_and_missing_titles():
    store = FakeStore()
    with pytest.raises(ValueError, match="timestamp"):
        run(store, {"media_type": "song", "title": "Song", "language": "es",
                    "chunks": [{"timestamp": [0, 1], "text": "a"}, {"text": "b"}]})
    with pytest.raises(ValueError, match="title"):
        run(store, {"media_type": "article", "language": "es", "chunks": [{"text": "a"}]})
    with pytest.raises(ValueError, match="series"):
        run(store, {"language": "es", "chunks": [{"timestamp": [0, 1], "text": "a"}]})


def test_make_media_id_includes_episode_coordinates():
    assert make_media_id("Élite!", 3, 7) == "elite-s03-e07"
