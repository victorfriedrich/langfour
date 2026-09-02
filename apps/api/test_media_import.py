import json

import pytest

from media_import import get_media, import_media, list_media, make_media_id
from paths import processed_file


def test_import_media_writes_catalog_and_recommender_file(tmp_path):
    payload = {
        "series": "La Casa Azul",
        "season": 1,
        "episode": 2,
        "language": "spanish",
        "model": "whisper-large-v3-turbo",
        "audio_seconds": 10.5,
        "chunks": [
            {"timestamp": [0, 2.5], "text": " Hola mundo. "},
            {"timestamp": [3, 5], "text": "Hasta luego."},
        ],
    }
    parser = lambda groups, source, language: [{"content": "hola", "id": 42}]

    result = import_media(payload, parser, lambda text: [text], tmp_path / "media", tmp_path / "processed")

    assert result["id"] == "la-casa-azul-s01-e02"
    assert result["chunks"][0]["text"] == "Hola mundo."
    catalog = list_media("es", tmp_path / "media")
    assert catalog[0]["series"] == "La Casa Azul"
    assert "chunks" not in catalog[0]
    assert get_media(result["id"], "spanish", tmp_path / "media")["chunks"][1]["text"] == "Hasta luego."
    processed = json.loads((tmp_path / str(processed_file("es","la-casa-azul-s01-e02"))).read_text())
    assert processed["content"] == [{"content": "hola", "id": 42}]
    assert processed["category"] == "Imported media"


def test_import_rejects_overlapping_chunks(tmp_path):
    payload = {
        "series": "Show",
        "language": "es",
        "chunks": [
            {"timestamp": [0, 3], "text": "One"},
            {"timestamp": [2, 4], "text": "Two"},
        ],
    }
    with pytest.raises(ValueError, match="overlaps"):
        import_media(payload, lambda *args: [], lambda text: [text], tmp_path / "media", tmp_path / "processed")


def test_make_media_id_includes_episode_coordinates():
    assert make_media_id("Élite!", 3, 7) == "elite-s03-e07"
