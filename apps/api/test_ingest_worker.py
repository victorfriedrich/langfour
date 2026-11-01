"""ingest_worker.py and the corpus_sync upload/pull it relies on."""

import gzip
import threading

import pytest

import corpus_sync
import ingest
import ingest_worker
from conftest import FakeSupabase


class StopAfter(threading.Event):
    """An Event whose wait() records the pause and stops the loop after `n`."""
    def __init__(self, n=1):
        super().__init__()
        self.pauses, self.n = [], n

    def wait(self, timeout=None):
        self.pauses.append(timeout)
        if len(self.pauses) >= self.n:
            self.set()
        return self.is_set()


def worker(monkeypatch, run_mix, stop, free=10 << 30):
    monkeypatch.setattr(ingest, "reclaim", lambda sb, lang, minutes: 0)
    monkeypatch.setattr(ingest, "run_mix", run_mix)
    ingest_worker.run_forever(FakeSupabase(), "es", {"proxy": 300}, stop,
                              publish=lambda *a: None, free_bytes=lambda: free)
    return stop.pauses


def test_an_outage_pauses_the_worker_instead_of_ending_it(monkeypatch):
    def run_mix(*a, **k):
        raise ingest.Outage("the caption proxy refuses requests (407)")
    assert worker(monkeypatch, run_mix, StopAfter()) == [ingest_worker.OUTAGE_PAUSE_S]


def test_any_other_error_is_a_short_pause(monkeypatch):
    def run_mix(*a, **k):
        raise ConnectionError("supabase dropped")
    assert worker(monkeypatch, run_mix, StopAfter()) == [ingest_worker.ERROR_PAUSE_S]


def test_an_empty_queue_waits_and_a_busy_one_goes_straight_on(monkeypatch):
    tallies = iter([{"proxy": {"done": 3, "failed": 1}}, {"proxy": {"done": 0, "failed": 0}}])
    calls = []

    def run_mix(sb, lang, mix, hours, **k):
        calls.append(k)
        return next(tallies)

    assert worker(monkeypatch, run_mix, StopAfter()) == [ingest_worker.EMPTY_PAUSE_S]
    assert len(calls) == 2 and calls[0]["cache_ready"] is True


def test_a_full_disk_pauses_before_claiming(monkeypatch):
    pauses = worker(monkeypatch, lambda *a, **k: pytest.fail("must not claim"),
                    StopAfter(), free=100 << 20)
    assert pauses == [ingest_worker.OUTAGE_PAUSE_S]


def test_the_worker_is_off_unless_configured(monkeypatch):
    monkeypatch.delenv("INGEST_WORKER_MIX", raising=False)
    assert ingest_worker.start(FakeSupabase()) is None
    monkeypatch.setenv("INGEST_WORKER_MIX", "proxy=300")
    monkeypatch.delenv("CAPTION_PROXY_URL", raising=False)
    assert ingest_worker.start(FakeSupabase()) is None    # proxy mix, no proxy
    monkeypatch.setenv("INGEST_WORKER_MIX", "proxi=300")
    assert ingest_worker.start(FakeSupabase()) is None    # typo: logged, not raised


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **_):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        from io import BytesIO
        return {"Body": BytesIO(self.objects[Key])}

    def get_paginator(self, name):
        objects = self.objects

        class Pages:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": k} for k in objects if k.startswith(Prefix)]}]
        return Pages()


def test_an_uploaded_transcript_comes_back_on_a_fresh_disk(corpus, monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(corpus_sync, "_s3", lambda write=False: s3)
    monkeypatch.setenv("LANGFIVE_CORPUS_BUCKET", "b")
    monkeypatch.setenv("LANGFIVE_CORPUS_PREFIX", "corpus/v1")
    (corpus / "abc_processed.json").write_text('{"id": "abc"}')
    corpus_sync.upload_transcript("es", "abc")
    assert gzip.decompress(s3.objects["corpus/v1/incoming/es/abc_processed.json.gz"]) == b'{"id": "abc"}'

    s3.objects["corpus/v1/incoming/es/../../evil_processed.json.gz"] = gzip.compress(b"x")
    (corpus / "abc_processed.json").unlink()
    assert corpus_sync.pull_incoming("es") == 1
    assert (corpus / "abc_processed.json").read_text() == '{"id": "abc"}'
    assert sorted(p.name for p in corpus.parent.rglob("*") if p.is_file()) == ["abc_processed.json"]
    assert corpus_sync.pull_incoming("es") == 0          # already on disk


def test_uploading_needs_its_own_write_token(monkeypatch):
    monkeypatch.delenv("LANGFIVE_CORPUS_WRITE_ACCESS_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="WRITE_ACCESS_KEY_ID"):
        corpus_sync._s3(write=True)
