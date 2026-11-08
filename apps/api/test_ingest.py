"""ingest.py against the shared in-memory queue fake (see conftest.py)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

import ingest
from conftest import FakeSupabase
from conftest import queued as pending

real_score = ingest.score     # the autouse fixtures below replace ingest.score
real_label = ingest.label     # and ingest.label


@pytest.fixture(autouse=True)
def scored(monkeypatch):
    """Record what run() hands to the scorer instead of calling Jev."""
    import video_quality
    calls = []
    monkeypatch.setattr(video_quality, "client", lambda: Mock())
    monkeypatch.setattr(ingest, "score", lambda sb, http, vid, lang: calls.append((vid, lang)))
    return calls


@pytest.fixture(autouse=True)
def labelled(monkeypatch):
    """Record what process() hands to the labeller instead of calling Jev."""
    import video_category
    calls = []
    monkeypatch.setattr(video_category, "client", lambda: Mock())
    monkeypatch.setattr(ingest, "label", lambda http, vid, lang: calls.append((vid, lang)))
    return calls


def test_label_sets_a_missing_topic_and_keeps_an_existing_one(corpus, monkeypatch):
    import video_category
    monkeypatch.setattr(video_category, "classify", lambda http, processed: "Cooking")
    (corpus / "new_processed.json").write_text(json.dumps({"title": "Tortilla de patatas"}))
    (corpus / "old_processed.json").write_text(json.dumps({"title": "Mukbang", "category": "Other"}))

    real_label(Mock(), "new", "es")
    real_label(Mock(), "old", "es")

    assert json.loads((corpus / "new_processed.json").read_text())["category"] == "Cooking"
    assert json.loads((corpus / "old_processed.json").read_text())["category"] == "Other"
    assert not list(corpus.glob("*.tmp"))


def test_a_labelling_failure_never_fails_the_video(corpus, monkeypatch, capsys):
    import video_category
    (corpus / "a_processed.json").write_text(json.dumps({"title": "t"}))

    def boom(*_args):
        raise RuntimeError("Jev HTTP 402")

    monkeypatch.setattr(video_category, "classify", boom)
    real_label(Mock(), "a", "es")
    assert "not labelled: RuntimeError: Jev HTTP 402" in capsys.readouterr().out
    assert json.loads((corpus / "a_processed.json").read_text()) == {"title": "t"}


def test_run_scores_finished_transcripts_only(corpus, monkeypatch, scored):
    (corpus / "a_processed.json").write_text("{}")
    monkeypatch.setattr(ingest, "prepare_cache", lambda: None)
    monkeypatch.setattr(ingest, "transcribe", lambda vid, lang, *_: ("failed", "boom"))
    sb = FakeSupabase([pending("a"), pending("b")])
    ingest.run(sb, "es", limit=5)
    assert scored == [("a", "es")]


def test_a_scoring_failure_never_fails_the_video(corpus, monkeypatch, capsys):
    import video_quality
    (corpus / "a_processed.json").write_text(json.dumps({"title": "t", "content": [{"content": "hola"}]}))

    def boom(*_args):
        raise RuntimeError("jev down")

    monkeypatch.setattr(video_quality, "score_and_store", boom)
    real_score(FakeSupabase([]), Mock(), "a", "es")
    assert "not scored: RuntimeError: jev down" in capsys.readouterr().out


def test_claim_is_compare_and_set():
    sb = FakeSupabase([pending("a"), pending("b", status="processing"),
                       pending("c", priority=10)])
    claimed = [r["video_id"] for r in ingest.claim(sb, "es", limit=5)]
    assert claimed == ["c", "a"]                 # priority first, b was taken
    assert sb.row("a")["status"] == "processing" and sb.row("a")["attempts"] == 1
    assert ingest.claim(sb, "es", limit=5) == []


def test_min_priority_leaves_discovery_rows_alone():
    sb = FakeSupabase([pending("disc"), pending("fav", priority=5)])
    assert [r["video_id"] for r in ingest.claim(sb, "es", limit=5, min_priority=1)] == ["fav"]
    assert sb.row("disc")["status"] == "pending"


def test_claim_respects_attempt_cap_and_language():
    sb = FakeSupabase([pending("worn", attempts=ingest.MAX_ATTEMPTS),
                       pending("german", lang="de")])
    assert ingest.claim(sb, "es", limit=5) == []


def test_run_treats_existing_transcript_as_done(corpus, monkeypatch):
    (corpus / "a_processed.json").write_text("{}")
    monkeypatch.setattr(ingest, "prepare_cache", lambda: None)
    monkeypatch.setattr(ingest, "transcribe", lambda *_: pytest.fail("must not transcribe"))
    sb = FakeSupabase([pending("a")])
    assert ingest.run(sb, "es", limit=5) == {"done": 1, "failed": 0}
    assert sb.row("a")["status"] == "done" and sb.row("a")["done_at"]


def test_run_records_failure_and_leaves_row_retryable(corpus, monkeypatch):
    monkeypatch.setattr(ingest, "prepare_cache", lambda: None)
    monkeypatch.setattr(ingest, "transcribe", lambda vid, lang, *_: ("failed", "boom"))
    sb = FakeSupabase([pending("a")])
    assert ingest.run(sb, "es", limit=5) == {"done": 0, "failed": 1}
    row = sb.row("a")
    assert (row["status"], row["error"], row["attempts"]) == ("failed", "boom", 1)


def test_run_dry_run_touches_nothing(corpus, monkeypatch):
    monkeypatch.setattr(ingest, "prepare_cache", lambda: pytest.fail("dry run parses nothing"))
    monkeypatch.setattr(ingest, "transcribe", lambda *_: pytest.fail("dry run"))
    sb = FakeSupabase([pending("a")])
    ingest.run(sb, "es", limit=5, dry_run=True)
    assert sb.row("a")["status"] == "pending"


def test_seed_done_prefers_disk_over_ledger(corpus, tmp_path):
    (corpus / "v1_processed.json").write_text("{}")
    ledger = tmp_path / "yt_es.json"
    ledger.write_text(json.dumps([{"ChannelId": "UC1", "Videos": [
        {"id": "v1", "processed": "failedrec"},
        {"id": "v2", "processed": "failedrec", "title": "bad"},
        {"id": "v3", "processed": "unprocessed"}]}]))
    sb = FakeSupabase([pending("v2", status="pending")])
    assert ingest.seed_done(sb, "es", ledger) == (1, 1)
    assert sb.row("v1")["status"] == "done" and sb.row("v1")["source"] == "legacy"
    v2 = sb.row("v2")
    assert v2["status"] == "failed" and v2["attempts"] == ingest.MAX_ATTEMPTS
    assert "v3" not in {r["video_id"] for r in sb.rows}


def test_submit_is_idempotent_and_never_resets_state():
    sb = FakeSupabase([pending("done", status="done")])
    assert ingest.submit(sb, "es", "new", "manual", 10) is True
    assert ingest.submit(sb, "es", "new", "manual", 10) is False
    assert ingest.submit(sb, "es", "done", "user", 0, submitted_by="u1") is False
    assert sb.row("done")["status"] == "done"
    assert sb.row("new")["priority"] == 10 and sb.row("new")["source"] == "manual"


def test_a_user_submission_queues_once_and_moves_pending_rows_up_only():
    sb = FakeSupabase([pending("disc"), pending("done", status="done"),
                       pending("failed", status="failed", priority=0),
                       pending("manual", priority=20)])

    assert ingest.submit_for_user(sb, "es", "new", "u1") == "pending"
    assert ingest.submit_for_user(sb, "es", "new", "u2") == "pending"
    new = [r for r in sb.rows if r["video_id"] == "new"]
    assert len(new) == 1 and new[0]["priority"] == 10 and new[0]["submitted_by"] == "u1"

    assert ingest.submit_for_user(sb, "es", "disc", "u1") == "pending"
    assert sb.row("disc")["priority"] == 10 and sb.row("disc")["source"] == "user"
    assert sb.row("disc")["submitted_by"] == "u1"
    assert ingest.submit_for_user(sb, "es", "done", "u1") == "done"
    assert ingest.submit_for_user(sb, "es", "failed", "u1") == "failed"
    assert sb.row("failed")["priority"] == 0
    assert ingest.submit_for_user(sb, "es", "manual", "u1") == "pending"
    assert sb.row("manual")["priority"] == 20


def test_reclaim_returns_only_stale_processing_rows():
    old = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    sb = FakeSupabase([pending("stale", status="processing", claimed_at=old),
                       pending("fresh", status="processing", claimed_at=ingest.now())])
    assert ingest.reclaim(sb, "es", older_than_minutes=120) == 1
    assert sb.row("stale")["status"] == "pending"
    assert sb.row("fresh")["status"] == "processing"


def test_counts_per_status():
    sb = FakeSupabase([pending("a"), pending("b", status="done"), pending("c", lang="de")])
    assert ingest.counts(sb, "es") == {"pending": 1, "processing": 0, "done": 1,
                                       "failed": 0, "skipped": 0}
    assert ingest.counts(sb, None)["pending"] == 2


def test_channel_id_recovered_from_the_legacy_link_shape():
    """The ledgers carry ChannelLink, not ChannelId. /channel/UC... resolves;
    an @handle cannot without an API call, so it stays NULL rather than wrong."""
    assert ingest.channel_id_of(
        {"ChannelLink": "https://www.youtube.com/channel/UCCNgRIfWQKZyPkNvHEzPh7Q"}
    ) == "UCCNgRIfWQKZyPkNvHEzPh7Q"
    assert ingest.channel_id_of({"ChannelLink": "https://www.youtube.com/@unsympathischTV"}) is None
    assert ingest.channel_id_of({}) is None


def test_counts_does_not_pass_a_kwarg_the_pinned_client_lacks():
    """postgrest 0.16 has select(*columns, count=None) and no `head`; the fake
    mirrors that signature, so this fails loudly if head=True comes back."""
    sb = FakeSupabase([pending("a"), pending("b", status="done")])
    assert ingest.counts(sb, "es")["pending"] == 1


def test_run_loads_the_word_cache_before_the_first_transcript(corpus, monkeypatch):
    """Without this, every token misses an empty cache and the miss path writes
    duplicate wordforms and flags healthy roots in the shared tables."""
    order = []
    monkeypatch.setattr(ingest, "prepare_cache", lambda: order.append("cache"))
    monkeypatch.setattr(ingest, "transcribe",
                        lambda vid, lang, *_: (order.append(vid), ("done", None))[1])
    ingest.run(FakeSupabase([pending("a"), pending("b")]), "es", limit=5)
    assert order == ["cache", "a", "b"]          # once, and before any parsing


def test_run_skips_the_cache_load_when_nothing_is_claimed(corpus, monkeypatch):
    monkeypatch.setattr(ingest, "prepare_cache", lambda: pytest.fail("nothing to parse"))
    assert ingest.run(FakeSupabase(), "es", limit=5) == {"done": 0, "failed": 0}


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=5IC69WoRYQ8", "5IC69WoRYQ8"),
    ("https://www.youtube.com/watch?v=5IC69WoRYQ8&pp=0gcJCX4JAYcqIYzv", "5IC69WoRYQ8"),
    ("https://www.youtube.com/watch?v=5IC69WoRYQ8&t=42s", "5IC69WoRYQ8"),
])
def test_watch_url_yields_a_bare_video_id(url, expected):
    """A watch URL often carries more than v=. Keeping the tail is what named
    46 transcripts '<id>&pp=0gcJ..._processed.json', and the recommender derives
    the video id it serves from that filename."""
    assert url.split("v=")[-1].split("&")[0] == expected


def test_dry_run_lists_exactly_what_run_would_claim(corpus, monkeypatch):
    """The two used to spell the ordering out separately, so a change to one
    made --dry-run advertise a different set than run() actually takes."""
    rows = [pending("low", score=0.1), pending("high", score=0.9),
            pending("urgent", priority=10, score=0.0),
            pending("worn", attempts=ingest.MAX_ATTEMPTS), pending("other", lang="de")]
    listed = [r["video_id"] for r in ingest.pending(FakeSupabase(rows), "es", 3)]
    claimed = []
    monkeypatch.setattr(ingest, "prepare_cache", lambda: None)
    monkeypatch.setattr(ingest, "transcribe",
                        lambda vid, lang, *_: (claimed.append(vid), ("done", None))[1])
    ingest.run(FakeSupabase(rows), "es", limit=3)
    # priority outranks score; the attempt-capped and other-language rows are
    # invisible to both. Same query, so the same answer, in the same order.
    assert listed == ["urgent", "high", "low"] == claimed


# ──────────────────────────────────────────────────────────────── mix ──

def test_parse_mix_reads_videos_per_method_and_rejects_typos():
    assert ingest.parse_mix("captions=20, whisper=30,proxy=150") == {
        "captions": 20, "whisper": 30, "proxy": 150}
    for bad in ("captions=20,whsiper=30", "proxy=lots", "captions=0", ""):
        with pytest.raises(ValueError):
            ingest.parse_mix(bad)


def test_each_methods_videos_are_spread_across_the_hour():
    order = ingest.hourly_order({"captions": 2, "whisper": 3, "proxy": 15})
    assert len(order) == 20 and order.count("whisper") == 3
    halves = order[:10], order[10:]
    assert [h.count("captions") for h in halves] == [1, 1]
    assert all(h.count("proxy") in (7, 8) for h in halves)


def test_run_mix_paces_claims_and_routes_each_method(corpus, monkeypatch):
    queue = [pending(f"v{i}") for i in range(10)]
    monkeypatch.setattr(ingest, "claim", lambda sb, lang, n, **k: [queue.pop(0)] if queue else [])
    monkeypatch.setattr(ingest, "finish", lambda *a, **k: None)
    monkeypatch.setattr(ingest, "prepare_cache", lambda: None)
    routes = []

    def transcribe(vid, lang, captions, proxy):
        routes.append((captions, proxy))
        (corpus / f"{vid}_processed.json").write_text("{}")
        return "done", None

    monkeypatch.setattr(ingest, "transcribe", transcribe)
    now, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s

    tally = ingest.run_mix(None, "es", {"captions": 1, "whisper": 1, "proxy": 2},
                           hours=1, clock=lambda: now[0], sleep=sleep)
    assert sorted(routes) == sorted([(True, False), (False, False), (True, True), (True, True)])
    assert slept == [900.0] * 3                       # 4 videos an hour: one every 15 min
    assert tally == {"captions": {"done": 1, "failed": 0}, "whisper": {"done": 1, "failed": 0},
                     "proxy": {"done": 2, "failed": 0}}


def test_run_mix_stops_when_the_queue_is_empty(corpus, monkeypatch):
    monkeypatch.setattr(ingest, "claim", lambda sb, lang, n, **k: [])
    monkeypatch.setattr(ingest, "transcribe", lambda *a: pytest.fail("nothing to do"))
    tally = ingest.run_mix(None, "es", {"proxy": 100}, hours=5, sleep=lambda s: None)
    assert tally == {"proxy": {"done": 0, "failed": 0}}


@pytest.mark.parametrize("error", [
    "DownloadError: ERROR: Unable to download API page: Tunnel connection failed: "
    "407 Proxy Authentication Required",
    "Exception: Error in processing transcript: Jev HTTP 402: Insufficient credits",
])
def test_an_outage_hands_the_row_back_and_stops_the_run(corpus, monkeypatch, error):
    """Failed rows are never retried, so a proxy out of traffic or OpenRouter
    out of credits must not fail the rest of the queue one video at a time."""
    monkeypatch.setattr(ingest, "prepare_cache", lambda: None)
    monkeypatch.setattr(ingest, "transcribe", lambda *_: ("failed", error))
    sb = FakeSupabase([pending("a"), pending("b")])
    with pytest.raises(ingest.Outage):
        ingest.run(sb, "es", limit=5)
    for vid in ("a", "b"):                       # b was claimed too, never tried
        assert (sb.row(vid)["status"], sb.row(vid)["attempts"]) == ("pending", 0)


def test_a_videos_own_failure_is_not_an_outage():
    assert ingest.outage_of("DownloadError: Video unavailable. This video is private") is None
    assert ingest.outage_of("Sign in to confirm your age") is None
    assert ingest.outage_of(None) is None


def test_publish_runs_before_done_and_its_failure_hands_the_row_back(corpus, monkeypatch, scored,
                                                                     labelled):
    def transcribe(vid, lang, *_):
        (corpus / f"{vid}_processed.json").write_text("{}")
        return "done", None

    monkeypatch.setattr(ingest, "transcribe", transcribe)
    published = []
    sb = FakeSupabase([pending("a"), pending("b")])
    row = ingest.claim(sb, "es", 1)[0]
    # Labelled before publishing, so the uploaded copy has its topic.
    assert ingest.process(sb, row, "es", ingest._Scorer(),
                          publish=lambda lang, vid: published.append((vid, list(labelled)))) == "done"
    assert published == [("a", [("a", "es")])] and sb.row("a")["status"] == "done"

    def down(lang, vid):
        raise ConnectionError("r2 unreachable")

    row = ingest.claim(sb, "es", 1)[0]
    with pytest.raises(ingest.Outage, match="publish"):
        ingest.process(sb, row, "es", ingest._Scorer(), publish=down)
    assert sb.row("b")["status"] == "pending" and scored == [("a", "es")]


def test_run_mix_can_be_stopped_and_can_skip_the_cache_load(corpus, monkeypatch):
    queue = [pending(f"v{i}") for i in range(5)]
    monkeypatch.setattr(ingest, "claim", lambda sb, lang, n, **k: [queue.pop(0)] if queue else [])
    monkeypatch.setattr(ingest, "finish", lambda *a, **k: None)
    monkeypatch.setattr(ingest, "prepare_cache", lambda: pytest.fail("the API's cache is loaded"))
    monkeypatch.setattr(ingest, "transcribe", lambda *a: ("failed", "boom"))
    stopped = iter([False, False, True])
    tally = ingest.run_mix(None, "es", {"proxy": 5}, hours=1, sleep=lambda s: None,
                           cache_ready=True, stopped=lambda: next(stopped))
    assert tally == {"proxy": {"done": 0, "failed": 2}} and len(queue) == 3
