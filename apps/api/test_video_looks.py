"""Model answer handling in video_looks.py."""
import httpx
import pytest

import video_looks


def answer(**over):
    return {"interest": 7, "trash": 2, "polish": 6, "sensitive": "none", "genre": "talk", **over}


def test_clean_keeps_only_the_columns():
    assert video_looks.clean(answer(why="ignored", id="x")) == answer()


@pytest.mark.parametrize(("given", "stored"), [
    ("none", "none"), ("MILD", "mild"), ("strong", "strong"), ("conspiracy", "strong"), ("politics", "mild"),
])
def test_clean_maps_off_list_sensitivity(given, stored):
    assert video_looks.clean(answer(sensitive=given))["sensitive"] == stored


def test_clean_bounds_scores_and_unknown_genres():
    got = video_looks.clean(answer(interest=11, trash=0, polish="6", genre="vlog"))
    assert (got["interest"], got["trash"], got["polish"], got["genre"]) == (10, 1, 6, "other")


def test_clean_raises_on_a_missing_score():
    bad = answer()
    del bad["trash"]
    with pytest.raises(KeyError):
        video_looks.clean(bad)


def http_with(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_prompt_no_longer_asks_for_a_reason():
    assert '"why"' not in video_looks.PROMPT


def test_judge_returns_the_verdict_and_its_cost():
    def handler(request):
        assert b"image_url" in request.content
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '```json\n{"interest": 7, "trash": 2, "polish": 6, "sensitive": "none", "genre": "talk"}\n```'}}],
            "usage": {"cost": 0.0003}})

    verdict, cost = video_looks.judge(http_with(handler), "t", "c", b"img")
    assert verdict == answer()
    assert cost == pytest.approx(0.0003)


def test_judge_stops_at_once_on_402():
    calls = []

    def handler(_request):
        calls.append(1)
        return httpx.Response(402, json={"error": "no credit"})

    with pytest.raises(video_looks.OutOfCredit):
        video_looks.judge(http_with(handler), "t", "c", b"img")
    assert len(calls) == 1


def test_judge_retries_a_bad_answer_and_counts_every_cost():
    replies = [{"choices": [{"message": {"content": "not json"}}], "usage": {"cost": 0.001}},
               {"choices": [{"message": {"content": '{"interest": 7, "trash": 2, "polish": 6}'}}], "usage": {"cost": 0.001}}]

    def handler(_request):
        return httpx.Response(200, json=replies.pop(0))

    verdict, cost = video_looks.judge(http_with(handler), "t", None, b"img")
    assert verdict["sensitive"] == "none" and verdict["genre"] == "other"
    assert cost == pytest.approx(0.002)


def test_thumbnail_is_none_when_youtube_has_none():
    http = http_with(lambda _r: httpx.Response(404, content=b"x" * 1097))
    assert video_looks.thumbnail(http, "gone") is None
