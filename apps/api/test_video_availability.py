"""The thumbnail sweep that hides videos gone from YouTube."""

import threading

import httpx

import video_availability as va

GONE, ALIVE = "gone0000000", "alive000000"
# Enough alive videos that one gone video stays under MAX_GONE_SHARE.
CORPUS = [f"video{i:06}" for i in range(10)]


def sweeper(answers: dict[str, int | Exception] | None = None) -> httpx.Client:
    answers = answers or {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        answer = answers.get(request.url.path.split("/")[2], 200)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer)

    return httpx.Client(transport=httpx.MockTransport(handler))


def run(http, ids, previous=frozenset(), stop=None):
    return va.sweep(http, [*ids, *CORPUS], set(previous), stop or threading.Event())


def test_a_404_is_gone_and_a_200_is_not():
    assert run(sweeper({GONE: 404}), [GONE, ALIVE]) == {GONE}


def test_a_video_that_comes_back_is_no_longer_gone():
    assert run(sweeper(), [GONE], previous={GONE}) == set()


def test_no_answer_keeps_the_previous_state():
    for failure in (403, 429, 500, httpx.ConnectTimeout("slow")):
        http = sweeper({GONE: failure, ALIVE: failure})
        assert run(http, [GONE, ALIVE], previous={GONE}) == {GONE}


def test_a_sweep_where_too_many_look_gone_is_ignored():
    http = sweeper(dict.fromkeys(CORPUS, 404))
    assert run(http, [], previous={CORPUS[0]}) == {CORPUS[0]}


def test_a_stopped_sweep_makes_no_requests_and_keeps_what_it_had():
    stop = threading.Event()
    stop.set()
    requests = []
    http = httpx.Client(transport=httpx.MockTransport(requests.append))
    assert run(http, [GONE, ALIVE], previous={ALIVE}, stop=stop) == {ALIVE}
    assert requests == []


def test_run_forever_publishes_each_sweep_and_survives_a_failure(monkeypatch):
    published = []
    stop = threading.Event()

    def publish(gone):
        published.append(gone)
        if len(published) == 1:
            raise RuntimeError("publish failed")
        stop.set()

    monkeypatch.setattr(va, "SWEEP_EVERY_S", 0)
    monkeypatch.setattr(va, "sweep", lambda _http, _ids, _previous, _stop: {GONE})
    va.run_forever([GONE], publish, stop)
    assert published == [{GONE}, {GONE}]
