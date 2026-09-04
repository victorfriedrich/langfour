"""Tests for ytpipeline's pure logic and its resume/dedup guarantees.

Deliberately not tested: the API client and the Common Crawl fetch. Both are
thin wrappers over network calls, and mocking them would test the mock.
"""

from datetime import date, timedelta
import gzip
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
from types import SimpleNamespace
import pytest

from conftest import FakeSupabase, queued

import ytpipeline as yp


# ─────────────────────────────────────────────────────────── duration ──

@pytest.mark.parametrize("iso,secs", [
    ("PT12M34S", 754), ("PT1H23M45S", 5025), ("PT45S", 45),
    ("PT2H", 7200), ("P1DT2H", 93600), ("PT0S", 0), ("", 0), ("junk", 0),
])
def test_seconds(iso, secs):
    assert yp.seconds(iso) == secs


def test_shorts_are_zero_minutes():
    """A 59s Short must floor to 0 minutes so select's >=60s filter drops it."""
    assert yp.seconds("PT59S") // 60 == 0


# ────────────────────────────────────────────────────── text cleaning ──

def test_clean_strips_the_noise_that_broke_detection():
    raw = "Réserve ta place : https://linktr.ee/akimomiri @akim #vlog"
    out = yp.clean(raw)
    assert "linktr.ee" not in out and "@akim" not in out and "#vlog" not in out
    assert "Réserve ta place" in out


@pytest.mark.parametrize("text", ["", None, "   ", "https://x.com/y"])
def test_clean_handles_empty(text):
    assert len(yp.clean(text)) < yp.MIN_CHARS


# ─────────────────────────────────────────────────────────── scoring ──

def test_score_prefers_more_views():
    assert yp.score(10, 100_000, 500, 200_000) > yp.score(10, 1_000, 500, 200_000)


def test_score_prefers_shorter_at_equal_views():
    assert yp.score(8, 50_000, 1_000, 100_000) > yp.score(25, 50_000, 1_000, 100_000)


def test_score_survives_a_single_video_channel():
    """lo == hi would divide by zero."""
    assert 0.0 <= yp.score(10, 5_000, 5_000, 5_000) <= 1.0


def test_score_preserves_view_signal_for_a_narrow_range():
    """Raising the low bound by 10% flattened close-but-distinct view counts."""
    assert yp.score(10, 105, 100, 105) > yp.score(10, 100, 100, 105)


# ──────────────────────────────────────────────────── harvest dedup ──

@pytest.fixture
def db(tmp_path):
    return yp.connect(tmp_path / "t.sqlite")


def insert_crawl(db, crawl, ids, monkeypatch=None, blocks=1):
    """Run the real harvest() for one crawl, with only the network faked.

    This used to paste harvest()'s own upsert, so the crawl_count tests passed
    against a copy and could not fail when harvest() regressed -- which is the
    exact regression the docstring below claims to guard. `blocks` repeats the
    ids across several index blocks of one crawl, which is how the inflated
    count happened in the first place."""
    payload = gzip.compress(
        "\n".join(f'{{"url": "https://www.youtube.com/channel/{c}"}}' for c in ids).encode())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(yp, "blocks_for", lambda _: [(f"shard{i}", 0, 1) for i in range(blocks)])
        mp.setattr(yp, "fetch", lambda *a, **k: payload)
        mp.setattr(yp.time, "sleep", lambda *_: None)
        yp.harvest(db, [crawl])


def test_crawl_count_counts_distinct_crawls(db):
    """The regression that inflated crawl_count to 32 across 28 crawls.

    Crawls arrive out of order, and a channel appears in several blocks of one
    crawl. Accumulating per crawl before writing makes the count structural.
    """
    cid = "UC" + "a" * 22
    insert_crawl(db, "CC-MAIN-2026-34", {cid}, blocks=3)  # newest first, 3 blocks
    insert_crawl(db, "CC-MAIN-2022-05", {cid}, blocks=2)  # then an older one
    row = db.execute("SELECT crawl_count, first_crawl, last_crawl "
                     "FROM channels").fetchone()
    assert row[0] == 2
    assert row[1] == "CC-MAIN-2022-05" and row[2] == "CC-MAIN-2026-34"


def test_crawl_count_never_exceeds_crawls_seen(db):
    cid = "UC" + "b" * 22
    crawls = ["CC-MAIN-2026-34", "CC-MAIN-2025-05", "CC-MAIN-2022-05"]
    for c in crawls:
        insert_crawl(db, c, {cid})
    assert db.execute("SELECT crawl_count FROM channels").fetchone()[0] == len(crawls)


def test_blocks_for_reads_past_the_first_512kb(monkeypatch):
    before = b"com,youtube)/channel. 0\tbefore\t0\t1\n"
    matches = b"".join(
        f"{yp.PREFIX}{i:06d} 0\tshard\t{i}\t1\n".encode()
        for i in range(15_000)
    )
    after = b"com,youtube)/channel0 0\tafter\t0\t1\n"
    blob = before + matches + after
    assert len(blob) > 512 * 1024
    monkeypatch.setattr(yp, "content_length", lambda _: len(blob))
    monkeypatch.setattr(
        yp, "fetch",
        lambda _url, rng=None, tries=4: blob if rng is None else blob[rng[0]:rng[1] + 1],
    )
    blocks = yp.blocks_for("CC-MAIN-test")
    assert len(blocks) == 15_001       # the preceding straddling block + all matches
    assert blocks[-1] == ("shard", 14_999, 1)


def test_unpublished_crawl_is_not_recorded_done(db, monkeypatch):
    monkeypatch.setattr(yp, "blocks_for", lambda _: None)
    yp.harvest(db, ["CC-MAIN-future"])
    assert db.execute("SELECT * FROM done WHERE stage='harvest'").fetchall() == []


def test_incomplete_crawl_block_is_not_recorded_done(db, monkeypatch):
    monkeypatch.setattr(yp, "blocks_for", lambda _: [("shard.gz", 0, 10)])
    monkeypatch.setattr(yp, "fetch", lambda *_args, **_kwargs: None)
    yp.harvest(db, ["CC-MAIN-incomplete"])
    assert db.execute("SELECT * FROM done WHERE stage='harvest'").fetchall() == []


# ──────────────────────────────────────────────────── channel parsing ──

def test_channel_row_keeps_hidden_subscribers_null():
    """0 would sink the channel to the bottom of every ranking as if it were dead."""
    item = {"id": "UC" + "c" * 22, "snippet": {"title": "x"},
            "statistics": {"hiddenSubscriberCount": True, "subscriberCount": "0",
                           "viewCount": "10", "videoCount": "2"}}
    assert yp.channel_row(item)[4] is None


def test_channel_row_stores_raw_payload():
    """Anything not broken out into a column must stay recoverable without quota."""
    item = {"id": "UC" + "d" * 22, "snippet": {"title": "t", "customUrl": "@t"},
            "statistics": {"subscriberCount": "5", "viewCount": "1", "videoCount": "1"}}
    raw = json.loads(yp.channel_row(item)[10])
    assert raw == item


def test_channel_row_flattens_topics():
    item = {"id": "UC" + "e" * 22, "snippet": {}, "statistics": {},
            "topicDetails": {"topicCategories": [
                "https://en.wikipedia.org/wiki/Entertainment"]}}
    assert json.loads(yp.channel_row(item)[7]) == ["Entertainment"]


# ─────────────────────────────────────────────────────────── resume ──

class RecordingYouTube:
    """Records which channels enrich() actually asked the API for."""

    used, budget = 0, 1_000

    def __init__(self):
        self.asked = []

    def channels(self, ids):
        self.asked.extend(ids)
        return [{"id": i, "snippet": {"title": i}, "statistics": {"subscriberCount": "1"}}
                for i in ids]


def enriched_by(db, stale_days=30):
    """What enrich() fetches -- from enrich(), not from a copy of its query."""
    yt = RecordingYouTube()
    yp.enrich(db, yt, stale_days)
    return yt.asked


def test_enrich_skips_already_enriched(db):
    db.execute("INSERT INTO channels (channel_id, enriched_at) "
               "VALUES ('UC1', datetime('now'))")
    db.execute("INSERT INTO channels (channel_id) VALUES ('UC2')")
    db.commit()
    assert enriched_by(db) == ["UC2"]


def test_enrich_refetches_stale_rows(db):
    """A monthly pipeline must refresh subscriber counts, not serve last month's."""
    db.execute("INSERT INTO channels (channel_id, enriched_at) "
               "VALUES ('UC1', datetime('now', '-40 days'))")
    db.commit()
    assert enriched_by(db) == ["UC1"]


def test_candidates_keeps_unknown_language(db):
    """Ambiguous channels stay in: description has weak recall, so it is used
    only to exclude. They are settled later by defaultAudioLanguage."""
    db.executemany("INSERT INTO channels (channel_id, uploads, subscribers, lang, "
                   "enriched_at) VALUES (?,?,?,?, datetime('now'))", [
                       ("UC_es", "UU_es", 50_000, "es"),
                       ("UC_none", "UU_none", 50_000, None),
                       ("UC_fr", "UU_fr", 50_000, "fr"),
                       ("UC_small", "UU_small", 100, None),
                   ])
    db.commit()
    got = {c for c, _ in yp.candidates(db, "es", 10_000)}
    assert got == {"UC_es", "UC_none"}      # fr excluded, small excluded


def test_candidates_keeps_hidden_subscriber_counts(db):
    db.execute("""INSERT INTO channels
                  (channel_id, uploads, subscribers, lang, enriched_at)
                  VALUES ('UC_hidden', 'UU_hidden', NULL, 'es', datetime('now'))""")
    db.commit()
    assert yp.candidates(db, "es", 10_000) == [("UC_hidden", "UU_hidden")]


def test_candidates_skips_cached_channels(db):
    """The whole point of the cache: a second language pays nothing for shared rows."""
    db.execute("INSERT INTO channels (channel_id, uploads, subscribers, videos_at) "
               "VALUES ('UC1','UU1',50000, datetime('now'))")
    db.commit()
    assert yp.candidates(db, None, 10_000) == []


# ──────────────────────────────────────────────────────────── locking ──

def test_lock_refuses_a_second_run(tmp_path):
    """flock: held for the life of the process and released by the kernel on
    any exit, so there is no stale file to detect and no pid to misread."""
    store = tmp_path / "t.sqlite"
    yp.lock(store)
    probe = subprocess.run([sys.executable, "-c", textwrap.dedent(f"""
        import sys, pathlib; sys.path.insert(0, {str(Path.cwd())!r})
        import ytpipeline as yp
        yp.lock(pathlib.Path({str(store)!r}))
    """)], capture_output=True, text=True)
    assert probe.returncode != 0 and "another run holds" in probe.stderr


# ──────────────────────────────────────────────────────── redaction ──

def test_redact_removes_the_key():
    leaked = ("<HttpError 403 when requesting https://youtube.googleapis.com/"
              "youtube/v3/channels?id=x&key=AIzaSyFAKE123 returned ...>")
    out = yp.redact(leaked)
    assert "AIzaSyFAKE123" not in out and "key=REDACTED" in out


def test_candidates_ordered_by_subscribers_hidden_last(db):
    """crawl_count used to lead here; being old and blog-linked is not the same
    as being worth 2 units. A hidden count is unknown, so it sorts last."""
    db.executemany("INSERT INTO channels (channel_id,uploads,subscribers,crawl_count,"
                   "enriched_at) VALUES (?,?,?,?, datetime('now'))", [
                       ("UC_big_rare", "UU1", 5_000_000, 1),
                       ("UC_mid_often", "UU2", 50_000, 30),
                       ("UC_hidden", "UU3", None, 12),
                   ])
    db.commit()
    assert [c for c, _ in yp.candidates(db, None, 10_000)] == [
        "UC_big_rare", "UC_mid_often", "UC_hidden"]


@pytest.mark.parametrize("langs,expected", [
    (["es"], None),
    (["es", "es"], None),
    (["es", "es", "en"], "es"),
    (["en", "es", "en", "es"], None),
    (["fr", "es", "fr", "es", "de"], None),
])
def test_audio_language_requires_supported_unique_majority(langs, expected):
    assert yp.audio_language(langs) == expected


def test_transient_video_error_remains_retryable(db):
    db.execute("""INSERT INTO channels
                  (channel_id, uploads, subscribers, lang, enriched_at)
                  VALUES ('UC1', 'UU1', 50000, 'es', datetime('now'))""")
    db.commit()

    class FailingYouTube:
        used, budget = 1, 10

        def playlist(self, *_):
            raise RuntimeError("temporary backend error")

    yp.videos(db, FailingYouTube(), "es", 10_000, 50)
    stamp, note = db.execute(
        "SELECT videos_at, note FROM channels WHERE channel_id='UC1'").fetchone()
    assert stamp is None
    assert note.startswith("videos_error:")
    assert yp.candidates(db, "es", 10_000) == [("UC1", "UU1")]


def test_enrich_clears_stale_detection_and_not_returned_note(db):
    db.execute("""INSERT INTO channels
                  (channel_id, enriched_at, lang, lang_conf, note)
                  VALUES ('UC1', datetime('now', '-40 days'), 'es', .99, 'not_returned')""")
    db.commit()

    class SuccessfulYouTube:
        used, budget = 1, 10

        def channels(self, *_):
            return [{"id": "UC1", "snippet": {"title": "new", "description": "new"},
                     "statistics": {"subscriberCount": "50000"}}]

    yp.enrich(db, SuccessfulYouTube(), 30)
    lang, conf, note = db.execute(
        "SELECT lang, lang_conf, note FROM channels WHERE channel_id='UC1'").fetchone()
    assert (lang, conf, note) == (None, None, None)


def test_detect_commits_resumable_batches(db, monkeypatch):
    db.executemany("""INSERT INTO channels
                      (channel_id, description, enriched_at)
                      VALUES (?, ?, datetime('now'))""",
                   [(f"UC{i}", "una descripcion espanola suficientemente larga")
                    for i in range(5)])
    db.commit()

    detected_language = SimpleNamespace(
        iso_code_639_1=SimpleNamespace(name="ES"))

    class Detector:
        def compute_language_confidence_values(self, _text):
            return [SimpleNamespace(value=.99, language=detected_language)]

    class Builder:
        @classmethod
        def from_languages(cls, *_languages):
            return cls()

        def with_preloaded_language_models(self):
            return self

        def build(self):
            return Detector()

    fake_lingua = SimpleNamespace(
        Language=SimpleNamespace(**{name: name for name in yp.DETECT_LANGS}),
        LanguageDetectorBuilder=Builder,
    )
    monkeypatch.setitem(sys.modules, "lingua", fake_lingua)
    statements = []
    db.set_trace_callback(statements.append)
    yp.detect(db, batch_size=2)
    assert db.execute("SELECT DISTINCT lang FROM channels").fetchall() == [("es",)]
    assert sum(statement == "COMMIT" for statement in statements) == 3


def test_report_survives_all_null_captions(db, capsys):
    db.execute("INSERT INTO channels (channel_id) VALUES ('UC1')")
    db.execute("INSERT INTO videos (video_id, channel_id, caption) VALUES ('v1', 'UC1', NULL)")
    db.commit()
    yp.report(db)
    assert "with captions" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "51", "not-a-number"])
def test_sample_size_rejects_values_outside_one_api_page(value):
    with pytest.raises(yp.argparse.ArgumentTypeError):
        yp.sample_size(value)


# The schema as it stood before this session, so an "upgrade in place" test
# upgrades something that actually existed. Copied deliberately rather than
# derived: the point is to pin the shape the 3 GB production store has.
PRE_UPGRADE_SCHEMA = """
CREATE TABLE channels (
    channel_id  TEXT PRIMARY KEY,
    crawl_count INTEGER DEFAULT 0,
    first_crawl TEXT, last_crawl TEXT,
    title TEXT, description TEXT, custom_url TEXT, country TEXT,
    subscribers INTEGER, views INTEGER, video_count INTEGER,
    topics TEXT, published_at TEXT, uploads TEXT, raw TEXT,
    lang TEXT, lang_conf REAL,
    enriched_at TEXT, videos_at TEXT,
    audio_lang TEXT, music_share REAL, latest_upload TEXT, note TEXT
);
CREATE TABLE videos (
    video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL,
    title TEXT, description TEXT, published_at TEXT,
    views INTEGER, likes INTEGER, comments INTEGER,
    duration_s INTEGER, category_id TEXT, audio_lang TEXT,
    caption TEXT, live TEXT
);
CREATE TABLE done (stage TEXT, key TEXT, at TEXT, PRIMARY KEY (stage, key));
"""


# ═══════════════════════════════════════════════════════════ selection ══

INSERT_VIDEO = yp.INSERT_VIDEO.format("REPLACE")


def add_channel(db, cid, subs=50_000, lang="es", **extra):
    cols = {"channel_id": cid, "title": cid, "subscribers": subs, "lang": lang,
            "enriched_at": "2026-01-01", "videos_at": "2026-01-01", "crawl_count": 5, **extra}
    db.execute(f"INSERT INTO channels ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
               list(cols.values()))
    db.commit()


def add_videos(db, cid, n, views=5_000, days_apart=7, duration=600, category="27",
               source="uploads", prefix="v"):
    rows = [(f"{prefix}{cid}{i}", cid, f"{prefix}{i}", "",
             (date(2025, 1, 1) + timedelta(days=i * days_apart)).isoformat(),
             views, 10, 1, duration, category, "es", "false", "none", source)
            for i in range(n)]
    db.executemany(INSERT_VIDEO, rows)
    db.commit()
    return [r[0] for r in rows]


def classified(**kw):
    return {"classified_at": "2026-01-01", "sensitivity": 0.1, "intellectuality": 0.5,
            **kw}


def test_store_upgrades_in_place(tmp_path):
    """A store built before the selection columns existed gets them on open."""
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.executescript(PRE_UPGRADE_SCHEMA + """
        INSERT INTO videos (video_id, channel_id, live) VALUES ('v1', 'UC1', 'none');""")
    old.commit(); old.close()
    for _ in range(2):                          # idempotent
        db = yp.connect(path)
        cols = {r[1] for r in db.execute("PRAGMA table_info(channels)")}
        assert {"expanded_at", "classified_at", "sensitivity"} <= cols
        assert db.execute("SELECT source FROM videos").fetchone() == ("uploads",)
        db.close()


BASE = dict(n=10, music_share=0.1, subscribers=100_000, avg_views=5_000, per_day=0.5,
            classified_at="2026-01-01", sensitivity=0.1, intellectuality=0.5)


@pytest.mark.parametrize("override,need_llm,expected", [
    ({}, True, None),
    ({"n": 3}, True, "sample"),
    ({"music_share": 0.9}, True, "music"),
    ({"music_share": None}, True, None),
    ({"avg_views": 500}, True, "engagement"),                    # 0.5% of subs
    ({"subscribers": None, "avg_views": 1}, True, None),          # hidden != zero
    ({"subscribers": 0, "avg_views": 0}, True, "engagement"),     # ...and 0 != hidden
    ({"per_day": 50}, True, "upload_rate"),
    ({"per_day": 2.5}, True, "upload_rate"),                      # broadcast news
    ({"per_day": 1.5}, True, None),                               # a daily vlogger
    ({"per_day": None}, True, None),                              # unparseable dates
    ({"intellectuality": 0.1}, True, "intellectuality"),
    ({"intellectuality": 0.1}, False, None),
    ({"intellectuality": None}, True, None),
    ({"classified_at": None}, False, None),
    ({"classified_at": None}, True, "unclassified"),
    ({"sensitivity": 0.9}, False, None),
    ({"sensitivity": 0.9}, True, "sensitivity"),
])
def test_reject_gates(override, need_llm, expected):
    assert yp.reject({**BASE, **override}, yp.Gates(), need_llm) == expected


def test_channel_stats_ignore_search_results(db):
    """search.list returns the most-viewed videos by construction. Letting them
    into the average would make every dead channel look alive."""
    add_channel(db, "UC1", subs=100_000)
    add_videos(db, "UC1", 10, views=100)                     # 0.1% of subs
    add_videos(db, "UC1", 10, views=1_000_000, source="search", prefix="s")
    passed, funnel = yp.qualified(db, "es", yp.Gates(), need_llm=False)
    assert passed == [] and funnel["engagement"] == 1


def test_upload_rate_comes_from_sample_span(db):
    add_channel(db, "UC_news", subs=1_000_000)
    add_videos(db, "UC_news", 50, views=50_000, days_apart=0)   # one day of output
    add_channel(db, "UC_weekly", subs=1_000_000)
    add_videos(db, "UC_weekly", 10, views=50_000, days_apart=7)
    passed, funnel = yp.qualified(db, "es", yp.Gates(), need_llm=False)
    assert [r["channel_id"] for r in passed] == ["UC_weekly"]
    assert funnel["upload_rate"] == 1


def test_select_filters_music_per_video_not_per_channel(db):
    """An artist's interview stays; their music videos go."""
    add_channel(db, "UC1", **classified(music_share=0.3))
    talk = add_videos(db, "UC1", 5)
    music = add_videos(db, "UC1", 2, category="10", prefix="m")
    picked = {r["video_id"] for r in yp.select(db, "es", yp.Gates())}
    assert picked == set(talk) and not picked & set(music)


def test_select_ranks_uploads_and_search_together(db):
    add_channel(db, "UC1", **classified())
    add_videos(db, "UC1", 6, views=1_000)
    best = add_videos(db, "UC1", 1, views=900_000, source="search", prefix="s")[0]
    rows = yp.select(db, "es", yp.Gates(), top_n=3)
    assert len(rows) == 3 and rows[0]["video_id"] == best
    assert {r["lang"] for r in rows} == {"es"}


def test_select_excludes_channels_that_fail_gates(db):
    add_channel(db, "UC_ok", **classified())
    add_videos(db, "UC_ok", 6)
    add_channel(db, "UC_unclassified")
    add_videos(db, "UC_unclassified", 6)
    add_channel(db, "UC_risky", **classified(sensitivity=0.9))
    add_videos(db, "UC_risky", 6)
    assert {r["channel_id"] for r in yp.select(db, "es", yp.Gates())} == {"UC_ok"}


def test_select_keeps_hidden_subscribers_and_null_views(db):
    add_channel(db, "UC_hidden", subs=None, **classified())
    add_videos(db, "UC_hidden", 6)
    db.execute("UPDATE videos SET views=NULL WHERE video_id='vUC_hidden0'")
    db.commit()
    rows = yp.select(db, "es", yp.Gates())
    assert len(rows) == 6 and all("score" in r for r in rows)


class StubResource:
    def __init__(self, items):
        self.items = items

    def list(self, **_):
        return self

    def execute(self):
        return {"items": self.items}


def test_search_costs_100_units():
    yt = yp.YouTube.__new__(yp.YouTube)
    yt.used, yt.budget = 0, 150
    yt.api = SimpleNamespace(search=lambda: StubResource([{"id": {"videoId": "a"}},
                                                          {"id": {"channelId": "no"}}]))
    assert yt.search("UC1") == ["a"] and yt.used == 100
    with pytest.raises(yp.Budget):              # 100 more would exceed 150
        yt.search("UC1")


class ExpandingYouTube:
    used, budget = 0, 1_000

    def search(self, cid, n=50):
        self.used += 100
        return ["vUC10", "new1"]                 # one already sampled, one new

    def videos(self, ids):
        self.used += 1
        return [{"id": i, "snippet": {"channelId": "UC1", "title": i, "publishedAt": "2025-06-01",
                                      "categoryId": "27"},
                 "statistics": {"viewCount": "999"}, "contentDetails": {"duration": "PT10M"}}
                for i in ids]


def test_expand_merges_without_overwriting_uploads(db):
    add_channel(db, "UC1", **classified())
    add_videos(db, "UC1", 6, views=5_000)
    yp.expand(db, ExpandingYouTube(), "es", yp.Gates())
    rows = dict(db.execute("SELECT video_id, source FROM videos"))
    assert rows["vUC10"] == "uploads" and rows["new1"] == "search"
    assert db.execute("SELECT views FROM videos WHERE video_id='vUC10'").fetchone() == (5_000,)
    assert db.execute("SELECT expanded_at FROM channels").fetchone()[0]


def test_expand_only_touches_channels_that_cleared_the_llm_gate(db):
    add_channel(db, "UC1")                      # never classified
    add_videos(db, "UC1", 6)
    yt = ExpandingYouTube()
    yp.expand(db, yt, "es", yp.Gates())
    assert yt.used == 0 and db.execute("SELECT expanded_at FROM channels").fetchone() == (None,)


def test_expand_stops_on_budget_without_stamping(db):
    add_channel(db, "UC1", **classified())
    add_videos(db, "UC1", 6)

    class Broke:
        used, budget = 9_000, 9_000

        def search(self, *_):
            raise yp.Budget("local budget reached")

    yp.expand(db, Broke(), "es", yp.Gates())
    assert db.execute("SELECT expanded_at FROM channels").fetchone() == (None,)


def test_classify_writes_verdicts_and_skips_done(db, monkeypatch):
    add_channel(db, "UC_new")
    add_videos(db, "UC_new", 6)
    add_channel(db, "UC_done", **classified())
    add_videos(db, "UC_done", 6)
    calls = []
    monkeypatch.setattr(yp, "verdict_for", lambda name, titles, lang: (
        calls.append((name, len(titles), lang)) or
        {"sensitivity": 0.2, "intellectuality": 0.8}))
    yp.classify(db, "es", yp.Gates(), limit=10, workers=2)
    assert calls == [("UC_new", 6, "es")]
    row = db.execute("SELECT sensitivity, intellectuality FROM channels "
                     "WHERE channel_id='UC_new'").fetchone()
    assert row == (0.2, 0.8)


def test_push_never_overwrites_an_existing_row():
    """The property the JSON worklist never had: a re-run must not reset the
    status of a video that ingestion already finished."""
    sb = FakeSupabase([queued("done_already", status="done")])
    rows = [{"video_id": "done_already", "lang": "es", "score": 0.1},
            {"video_id": "fresh", "lang": "es", "score": 0.9}]
    assert yp.push(rows, sb) == 1                     # only 'fresh' counts as written
    assert sb.row("done_already")["status"] == "done"
    assert sb.row("fresh")["status"] == "pending"


def test_push_chunks_large_batches():
    sb = FakeSupabase()
    rows = [{"video_id": str(i), "lang": "es", "score": 0.5} for i in range(1_001)]
    assert yp.push(rows, sb) == 1_001
    assert len(sb.calls) == 3                         # 500 + 500 + 1


def test_push_refuses_unsupported_language():
    with pytest.raises(ValueError):
        yp.push([{"video_id": "x", "lang": "xx"}], FakeSupabase())


def test_missing_uploads_playlist_is_permanent(db):
    db.execute("""INSERT INTO channels (channel_id, uploads, subscribers, lang, enriched_at)
                  VALUES ('UC1', 'UU1', 50000, 'es', datetime('now'))""")
    db.commit()

    class Vanished:
        used, budget = 1, 10

        def playlist(self, *_):
            raise yp.Gone("playlist not found")

    yp.videos(db, Vanished(), "es", 10_000, 50)
    stamp, note = db.execute("SELECT videos_at, note FROM channels").fetchone()
    assert stamp and note == "no_uploads"
    assert yp.candidates(db, "es", 10_000) == []


# ══════════════════════════════════════════════════ api error classification ══

def http_error(status, reason=None, key="SECRET123"):
    """A real googleapiclient HttpError carrying a realistic YouTube body.

    Realistic matters: with no top-level `message` the client renders the
    reason as "Ok" and leaves error_details empty, which is not what the API
    ever sends and would let a broken classifier pass."""
    import httplib2
    from googleapiclient.errors import HttpError
    error = {"code": status, "message": f"request failed with {reason or status}"}
    if reason:
        error["errors"] = [{"reason": reason, "domain": "youtube.quota",
                            "message": error["message"]}]
    body = json.dumps({"error": error}).encode()
    return HttpError(httplib2.Response({"status": status, "reason": "Forbidden"}), body,
                     uri=f"https://youtube.googleapis.com/youtube/v3/videos?key={key}")


def calling(exc, budget=100):
    """Drive YouTube._call with a resource that raises `exc`."""
    yt = yp.YouTube.__new__(yp.YouTube)
    yt.used, yt.budget = 0, budget

    class Raiser:
        def list(self, **_):
            raise exc

    yt.api = SimpleNamespace(videos=lambda: Raiser())
    return yt


@pytest.mark.parametrize("status,reason,expected", [
    (404, None, yp.Gone),                       # playlist/channel deleted
    (410, None, yp.Gone),
    (403, "quotaExceeded", yp.Budget),          # the day is over
    (403, "dailyLimitExceeded", yp.Budget),
    (403, "channelSuspended", yp.Gone),         # never coming back
    (403, "userRateLimitExceeded", RuntimeError),  # slow down, then retry
    (500, None, RuntimeError),
])
def test_api_errors_are_classified_by_status_not_by_rendered_text(status, reason, expected,
                                                                  monkeypatch):
    """403 is three different things -- day over, slow down, gone for good --
    and status_code cannot tell them apart, so the reason code does."""
    monkeypatch.setattr(yp.time, "sleep", lambda *_: None)
    with pytest.raises(expected) as caught:
        calling(http_error(status, reason)).videos(["v1"])
    # Budget and Gone are RuntimeErrors, so assert the exact type.
    assert type(caught.value) is expected


def test_permanent_errors_are_not_retried(monkeypatch):
    """A 404 must cost one call, not three: search.list is 100 units each."""
    slept = []
    monkeypatch.setattr(yp.time, "sleep", lambda n: slept.append(n))
    with pytest.raises(yp.Gone):
        calling(http_error(404)).videos(["v1"])
    assert slept == []


def test_the_api_key_never_reaches_the_stored_message(monkeypatch):
    """str(HttpError) renders the full request URL, key included."""
    monkeypatch.setattr(yp.time, "sleep", lambda *_: None)
    for status in (404, 500):
        with pytest.raises(RuntimeError) as caught:
            calling(http_error(status)).videos(["v1"])
        assert "SECRET123" not in str(caught.value)
        assert "key=REDACTED" in str(caught.value)


def test_expand_stamps_a_vanished_channel_instead_of_rebuying_it(db):
    """Without the stamp this channel costs 100 units on every future run."""
    add_channel(db, "UC1", **classified())
    add_videos(db, "UC1", 6)

    class Vanished:
        used, budget = 0, 1_000

        def search(self, *_, **__):
            self.used += 100
            raise yp.Gone("channel not found")

    yp.expand(db, Vanished(), "es", yp.Gates())
    stamp, note = db.execute("SELECT expanded_at, note FROM channels").fetchone()
    assert stamp and note == "no_search"
    passed, _ = yp.qualified(db, "es", yp.Gates(), need_llm=True)
    assert [r["expanded_at"] for r in passed] == [stamp]      # not a candidate again


# ═════════════════════════════════════════════════════════ schema/column drift ══

def test_video_cols_match_the_schema_in_a_fresh_and_an_upgraded_store(tmp_path):
    """The bug this guards: a column added to SCHEMA but not ADDED_COLUMNS, or
    added mid-CREATE-TABLE so a fresh store and an ALTER-upgraded one disagree
    on order. Both stores must expose exactly VIDEO_COLS, in order."""
    fresh = yp.connect(tmp_path / "fresh.sqlite")
    assert tuple(r[1] for r in fresh.execute("PRAGMA table_info(videos)")) == yp.VIDEO_COLS

    old = sqlite3.connect(tmp_path / "old.sqlite")
    old.executescript(PRE_UPGRADE_SCHEMA)
    old.commit(); old.close()
    upgraded = yp.connect(tmp_path / "old.sqlite")
    assert tuple(r[1] for r in upgraded.execute("PRAGMA table_info(videos)")) == yp.VIDEO_COLS
    # channels is additive-only: an upgraded store keeps latest_upload, which a
    # fresh one never gets. Every column the code READS must exist in both.
    fresh_ch = {r[1] for r in fresh.execute("PRAGMA table_info(channels)")}
    upgraded_ch = {r[1] for r in upgraded.execute("PRAGMA table_info(channels)")}
    assert fresh_ch <= upgraded_ch
    assert {"expanded_at", "classified_at", "sensitivity", "intellectuality"} <= fresh_ch


def test_insert_names_its_columns_so_order_cannot_silently_shift(db):
    """A positional INSERT writes every value one column off when the orders
    disagree, with no error. Naming them makes that impossible."""
    assert "INSERT OR REPLACE INTO videos (" + ", ".join(yp.VIDEO_COLS) in \
        yp.INSERT_VIDEO.format("REPLACE")
    add_channel(db, "UC1")
    db.execute(yp.INSERT_VIDEO.format("REPLACE"),
               ("v1", "UC1", "t", "", "2025-01-01", 5, 1, 1, 600, "27", "es",
                "false", "none", "uploads"))
    db.commit()
    assert db.execute("SELECT title, duration_s, source FROM videos").fetchone() == \
        ("t", 600, "uploads")


def test_zero_subscribers_is_a_real_count_not_a_hidden_one():
    """9,618 channels report 0. `if r["subscribers"]` treated them like a hidden
    count and waved them through a ratio no view total can clear; the naive
    repair (`is not None`) divides by zero instead."""
    row = {**BASE, "subscribers": 0, "avg_views": 5_000}
    assert yp.reject(row, yp.Gates(min_subs=0), True) == "engagement"
    # ...unless the gate is switched off, in which case there is nothing to fail.
    assert yp.reject(row, yp.Gates(min_subs=0, min_views_per_sub=0), True) is None


def test_an_item_without_a_channel_id_is_dropped_by_both_stages():
    """channel_id is NOT NULL, and the verbs disagree about a violation: OR
    REPLACE aborts the whole executemany with an IntegrityError neither except
    clause catches, OR IGNORE drops the row silently."""
    good = {"id": "v1", "snippet": {"channelId": "UC1", "title": "t",
                                    "publishedAt": "2025-01-01", "categoryId": "27"},
            "statistics": {"viewCount": "5"}, "contentDetails": {"duration": "PT10M"}}
    orphan = {"id": "v2", "snippet": {"title": "no channel"},
              "statistics": {}, "contentDetails": {"duration": "PT10M"}}
    for source in ("uploads", "search"):
        rows = yp.video_rows([good, orphan], source)
        assert [r[0] for r in rows] == ["v1"] and rows[0][-1] == source


def test_both_insert_verbs_survive_an_orphan_item(db):
    add_channel(db, "UC1")
    orphan = {"id": "v2", "snippet": {"title": "no channel"},
              "statistics": {}, "contentDetails": {"duration": "PT10M"}}
    for verb in ("REPLACE", "IGNORE"):
        db.executemany(yp.INSERT_VIDEO.format(verb), yp.video_rows([orphan]))   # no raise
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0


def test_classify_writes_every_verdict_when_run_concurrently(db, monkeypatch):
    """Requests run in a pool; reads and writes stay on this thread, so every
    channel must still get exactly one verdict and one commit."""
    for i in range(12):
        add_channel(db, f"UC{i}")
        add_videos(db, f"UC{i}", 6)
    monkeypatch.setattr(yp, "verdict_for", lambda name, titles, lang:
                        {"sensitivity": 0.1, "intellectuality": 0.7})
    yp.classify(db, "es", yp.Gates(), limit=100, workers=4)
    rows = db.execute("SELECT COUNT(*), COUNT(classified_at) FROM channels").fetchone()
    assert rows == (12, 12)


def test_classify_survives_one_failing_channel(db, monkeypatch):
    for i in range(4):
        add_channel(db, f"UC{i}")
        add_videos(db, f"UC{i}", 6)

    def flaky(name, titles, lang):
        if name == "UC2":
            raise RuntimeError("provider said no")
        return {"sensitivity": 0.1, "intellectuality": 0.7}

    monkeypatch.setattr(yp, "verdict_for", flaky)
    yp.classify(db, "es", yp.Gates(), limit=100, workers=4)
    assert db.execute("SELECT COUNT(classified_at) FROM channels").fetchone()[0] == 3
    assert db.execute("SELECT classified_at FROM channels WHERE channel_id='UC2'"
                      ).fetchone()[0] is None          # retried on the next run
