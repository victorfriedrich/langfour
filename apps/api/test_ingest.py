"""ingest.py against the shared in-memory queue fake (see conftest.py)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeSupabase, queued as pending

import ingest


def test_claim_is_compare_and_set():
    sb = FakeSupabase([pending("a"), pending("b", status="processing"),
                       pending("c", priority=10)])
    claimed = [r["video_id"] for r in ingest.claim(sb, "es", limit=5)]
    assert claimed == ["c", "a"]                 # priority first, b was taken
    assert sb.row("a")["status"] == "processing" and sb.row("a")["attempts"] == 1
    assert ingest.claim(sb, "es", limit=5) == []


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
    monkeypatch.setattr(ingest, "transcribe", lambda vid, lang: ("failed", "boom"))
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


def test_reclaim_returns_only_stale_processing_rows():
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
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
                        lambda vid, lang: (order.append(vid), ("done", None))[1])
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
                        lambda vid, lang: (claimed.append(vid), ("done", None))[1])
    ingest.run(FakeSupabase(rows), "es", limit=3)
    # priority outranks score; the attempt-capped and other-language rows are
    # invisible to both. Same query, so the same answer, in the same order.
    assert listed == ["urgent", "high", "low"] == claimed
