"""ai_gateway: every AI call goes through it, names its source, and is counted.

Three layers, so a call that slips past the gateway fails the build:

1. The guard in conftest.py fails ANY test whose code reaches an AI host
   without the gateway. The first tests here prove the guard catches each way
   out (httpx, the openai SDK, requests, urllib).
2. Feature tests drive every feature that spends money with a fake provider
   and check the spend landed under that feature's source. A feature rewired
   to its own client trips the guard here.
3. A source scan catches code no test runs yet: no module but ai_gateway may
   name an AI host, read an AI key or import openai, and every source a call
   names must be registered.
"""

import ast
import asyncio
import json
import os
import re
import urllib.request

# The features below import the Supabase client, which refuses to load
# without these; no test here reaches Supabase.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("REQUIRE_SERVICE_ROLE", "0")
os.environ.setdefault(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.test-signature",
)
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import requests
from pydantic import BaseModel

import ai_gateway
from conftest import BypassedGateway

API = Path(__file__).parent


# --- 1. The guard catches every way around the gateway ----------------------

def _expect_bypass(guard, call):
    with pytest.raises(BypassedGateway):
        call()
    assert guard, "the guard should have recorded the bypass"
    guard.clear()   # expected here; any other test with a bypass fails


def test_guard_catches_a_raw_httpx_client(ai_spend_guard):
    _expect_bypass(ai_spend_guard, lambda: httpx.Client().post(ai_gateway.JEV_URL, json={}))


def test_guard_catches_a_raw_async_httpx_client(ai_spend_guard):
    async def call():
        async with httpx.AsyncClient() as client:
            await client.post(ai_gateway.JEV_URL, json={})
    _expect_bypass(ai_spend_guard, lambda: asyncio.run(call()))


def test_guard_catches_a_raw_openai_sdk_client(ai_spend_guard):
    from openai import APIConnectionError, OpenAI
    client = OpenAI(base_url=ai_gateway.OPENROUTER_BASE_URL, api_key="k", max_retries=0)
    with pytest.raises(APIConnectionError):   # the SDK wraps transport errors
        client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    assert ai_spend_guard
    ai_spend_guard.clear()


def test_guard_catches_requests_and_urllib(ai_spend_guard):
    _expect_bypass(ai_spend_guard, lambda: requests.post(
        ai_gateway.ELEVENLABS_TTS_URL.format(voice_id="v"), json={}, timeout=1))
    # Through a proxy the socket only sees the proxy's host.
    _expect_bypass(ai_spend_guard, lambda: requests.post(
        ai_gateway.JEV_URL, json={}, timeout=1, proxies={"https": "http://127.0.0.1:9"}))
    _expect_bypass(ai_spend_guard, lambda: urllib.request.urlopen(
        "https://api.deepinfra.com/v1/openai/models", timeout=1))


def test_guard_catches_a_gateway_call_the_test_did_not_fake(ai_spend_guard):
    _expect_bypass(ai_spend_guard, lambda: ai_gateway.http_client("video.quality").post(
        ai_gateway.JEV_URL, json={}))


# --- The gateway itself -------------------------------------------------------

def test_chat_is_attributed_to_its_source_on_openrouter_and_in_the_ledger(ai_upstream):
    with ai_gateway.recording() as calls:
        ai_gateway.chat("reader.translate_section", model="deepseek/x",
                        messages=[{"role": "user", "content": "hola"}])
    (sent,) = ai_upstream.requests
    body = json.loads(sent.content)
    # A Referer makes OpenRouter register an app, so the tag is the private
    # `user` field, and the app attribution stays opt-in.
    assert "HTTP-Referer" not in sent.headers
    assert ai_gateway.SOURCE_HEADER not in sent.headers      # ours, not OpenRouter's
    assert body["user"] == "reader.translate_section"
    assert body["usage"] == {"include": True}                 # so the cost comes back
    (call,) = calls
    assert (call.source, call.provider, call.model, call.cost) == (
        "reader.translate_section", "openrouter", "deepseek/x", ai_upstream.COST)
    assert (call.input_tokens, call.output_tokens, call.generation_id) == (10, 2, "gen-test")


def test_raw_jev_requests_record_their_cost(ai_upstream):
    with ai_gateway.recording() as calls, ai_gateway.http_client("video.quality") as http:
        http.post(ai_gateway.JEV_URL, json={"model": "typesafe/jev-1.13", "state": {},
                                            "questions": {"q": {"type": "noul"}}})
        http.get(ai_gateway.CREDITS_URL)   # not billed, so not counted
    assert [(c.source, c.model, c.cost) for c in calls] == [
        ("video.quality", "typesafe/jev-1.13", ai_upstream.COST)]
    jev = json.loads(ai_upstream.requests[0].content)
    assert jev["user"] == "video.quality"   # OpenRouter's external_user, per generation
    assert jev["questions"] == {"q": {"type": "noul"}}


def test_the_app_attribution_header_stays_opt_in(ai_upstream, monkeypatch):
    monkeypatch.setattr(ai_gateway, "SITE_URL", "https://app.langfour.com")
    with ai_gateway.http_client("video.quality") as http:
        http.post(ai_gateway.JEV_URL, json={"model": "jev", "state": {}, "questions": {}})
    (sent,) = ai_upstream.requests
    assert sent.headers["HTTP-Referer"] == "https://app.langfour.com"   # one app, not one per source
    assert sent.headers["X-Title"] == ai_gateway.APP_NAME


def test_every_retry_of_structured_output_is_billed_to_the_source(ai_upstream):
    class Out(BaseModel):
        ok: bool

    ai_upstream.chat_content = "not json"
    with ai_gateway.recording() as calls, pytest.raises(RuntimeError):
        ai_gateway.parse_structured("parse.word_root", model="m", messages=[], schema_model=Out)
    assert [c.source for c in calls] == ["parse.word_root"] * 3


def test_an_unregistered_source_is_refused_before_any_request(ai_upstream):
    for call in (lambda: ai_gateway.chat("mystery", model="m", messages=[]),
                 lambda: ai_gateway.http_client("mystery"),
                 lambda: ai_gateway.async_http_client("mystery"),
                 lambda: ai_gateway.transcribe("mystery", model="m", file=b"")):
        with pytest.raises(ai_gateway.UnknownSource):
            call()
    assert ai_upstream.requests == []


def test_a_gateway_transport_refuses_a_request_without_a_source(ai_upstream):
    with httpx.Client(transport=ai_gateway._Metered()) as http, \
            pytest.raises(ai_gateway.MissingSource):
        http.post(ai_gateway.JEV_URL, json={})
    assert ai_upstream.requests == []


def test_the_ledger_sums_calls_per_source_and_flushes_them(ai_upstream, monkeypatch):
    written = []
    monkeypatch.setattr(ai_gateway, "_write", written.append)
    ai_gateway.ledger.take()
    with ai_gateway.http_client("words.importance") as http:
        for _ in range(3):
            http.post(ai_gateway.JEV_URL, json={"model": "jev", "state": {}, "questions": {}})
    ai_gateway.chat("translate_word", model="flash", messages=[])
    ai_gateway.ledger.flush()
    (rows,) = written
    by_source = {r["source"]: r for r in rows}
    assert by_source["words.importance"]["calls"] == 3
    assert by_source["words.importance"]["cost_usd"] == pytest.approx(3 * ai_upstream.COST)
    assert by_source["words.importance"]["input_tokens"] == 30
    assert by_source["translate_word"]["model"] == "flash"
    assert {r["origin"] for r in rows} == {ai_gateway.ORIGIN}
    ai_gateway.ledger.flush()
    assert len(written) == 1   # nothing new, nothing written


def test_a_failed_spend_write_never_breaks_the_caller(ai_upstream, monkeypatch, caplog):
    def broken(rows):
        raise RuntimeError("relation ai_spend does not exist")
    monkeypatch.setattr(ai_gateway, "_write", broken)
    ai_gateway.chat("translate_word", model="flash", messages=[])
    with caplog.at_level("INFO", logger="ai_gateway"):
        ai_gateway.ledger.flush()
    assert "translate_word 1 calls" in caplog.text
    assert "could not write" in caplog.text
    written = []
    monkeypatch.setattr(ai_gateway, "_write", written.append)
    ai_gateway.ledger.flush()   # the next flush retries what failed
    assert [(r["source"], r["calls"]) for r in written[0]] == [("translate_word", 1)]


def test_failed_calls_are_counted_as_errors(ai_upstream):
    ai_upstream.route = lambda request: httpx.Response(402, json={"error": "no credit"})
    ai_gateway.ledger.take()
    with ai_gateway.http_client("video.looks") as http:
        http.post(ai_gateway.CHAT_URL, json={"model": "gemini"})
    (row,) = ai_gateway.ledger.take()
    assert (row["calls"], row["errors"], row["cost_usd"]) == (1, 1, 0)


# --- 2. Every paid feature spends through the gateway, under its own source ---

def _video_quality(fake, mp):
    import video_quality
    video_quality.ask(video_quality.client(), "Un título", ["hola"] * 400)


def _video_category(fake, mp):
    import video_category
    video_category.classify(video_category.client(), {"title": "t", "content": [{"content": "hola"}]})


def _video_looks(fake, mp):
    import video_looks
    fake.chat_content = json.dumps({"interest": 5, "trash": 2, "polish": 6,
                                    "sensitive": "none", "genre": "talk"})
    video_looks.judge(video_looks.client(), "Un título", "Canal", b"jpeg")


def _attach_word(fake, mp):
    import word_matching
    with word_matching.jev_client() as http:
        word_matching.ask_jev(http, "casas", ["la casa"], "es")


def _language_check(fake, mp):
    import language_check
    mp.setattr(language_check, "enabled_for", lambda user_id: True)
    payload = language_check.CheckRequest(language="es", blocks=[
        language_check.Block(text="hola amigo", words=[(0, 4), (5, 10)])])
    asyncio.run(language_check.language_check(payload, SimpleNamespace(id="u1")))


def _word_importance(fake, mp):
    import word_importance
    mp.setattr(word_importance, "roots_of", lambda sb, language, ids: {1: "hola", 2: "el amigo"})
    asyncio.run(word_importance.rank(None, "es", "video", "t", "hola amigo",
                                     [("hola", 1), ("amigo", 2)]))


def _word_familiarity(fake, mp):
    import word_familiarity
    mp.setattr(word_familiarity, "word_entries", lambda sb, ids: {1: {"root": "hola"}})
    mp.setattr(word_familiarity, "vocabulary", lambda sb, user, language: ([], []))
    table = SimpleNamespace(upsert=lambda *a, **k: SimpleNamespace(execute=lambda: None))
    sb = SimpleNamespace(table=lambda name: table)
    asyncio.run(word_familiarity.rate(sb, "u1", "es", ["en"], [1]))


def _channel_verdict(fake, mp):
    import ytpipeline
    fake.chat_content = json.dumps({"sensitivity": 0.1, "intellectuality": 0.6})
    ytpipeline.verdict_for("Canal", ["Un vídeo"], "es")


def _nlp(name, *args):
    def run(fake, mp):
        import nlp_processing
        getattr(nlp_processing, name)(*args)
    return run


def _translate_word(fake, mp):
    import database
    rows = {"data": [{"id": 1, "root": "la casa", "translation": None, "language": "es"}]}
    query = SimpleNamespace()
    for method in ("select", "eq", "update", "limit", "single", "maybe_single"):
        setattr(query, method, lambda *a, **k: query)
    query.execute = lambda: SimpleNamespace(**rows)
    mp.setattr(database, "supabase", SimpleNamespace(table=lambda name: query))
    database.get_or_create_translation(1, "es")


def _tts(fake, mp):
    import tts
    mp.setenv("ELEVENLABS_API_KEY", "el-test")
    tts._synthesize("hola", "es")


def _whisper(fake, mp, tmp_path):
    import videoparsing
    audio = tmp_path / "piece.m4a"
    audio.write_bytes(b"")
    videoparsing.whisper(str(audio), "es")


FEATURES = [
    ("video.quality", _video_quality),
    ("video.category", _video_category),
    ("video.looks", _video_looks),
    ("parse.attach_word", _attach_word),
    ("reader.language_check", _language_check),
    ("words.importance", _word_importance),
    ("words.familiarity", _word_familiarity),
    ("pipeline.channel_verdict", _channel_verdict),
    ("parse.filter_entities", _nlp("filter_entities", "Hola Juan", "es")),
    ("parse.word_root", _nlp("get_word_root", "casas", "es")),
    ("parse.alternatives", _nlp("generate_alternatives", "la casa", "noun", "es")),
    ("parse.verify_translate", _nlp("verify_and_translate", "la casa", "noun", ["casas"], "es")),
    ("parse.verify_language", _nlp("verify_language", ["casa"], "es")),
    ("reader.summarize", _nlp("summarize_text", "Un texto largo.")),
    ("reader.translate_section", _nlp("translate_section", "Hola.", "es")),
    ("reader.word_examples", _nlp("generate_word_examples", ["casa"], "es")),
    ("translate_word", _translate_word),
    ("tts", _tts),
    ("video.transcribe", _whisper),
]


@pytest.mark.parametrize("source,feature", FEATURES, ids=[s for s, _ in FEATURES])
def test_each_paid_feature_spends_through_the_gateway_under_its_source(
        source, feature, ai_upstream, monkeypatch, tmp_path):
    # The fake's answers need not suit every feature: what is checked is
    # where the request went, not what the feature made of the reply.
    with ai_gateway.recording() as calls, suppress(Exception):
        if feature is _whisper:
            feature(ai_upstream, monkeypatch, tmp_path)
        else:
            feature(ai_upstream, monkeypatch)
    assert ai_upstream.requests, f"{source}: the feature made no AI request"
    assert {c.source for c in calls} == {source}


def test_every_registered_source_has_a_feature_test_or_is_a_script():
    tested = {s for s, _ in FEATURES} | {"pipeline.channel_judge"}   # test_ytpipeline.py
    untested = {s for s in ai_gateway.SOURCES if not s.startswith("script.")} - tested
    assert not untested, f"add a FEATURES entry for {sorted(untested)}"


# --- 3. The source scan: what no test runs yet -------------------------------

ALLOWED = {"ai_gateway.py", "conftest.py", "test_ai_gateway.py"}
FORBIDDEN = [
    (re.compile(r"openrouter\.ai|api\.deepinfra\.com|api\.elevenlabs\.io"), "names an AI host"),
    (re.compile(r"""(environ\[|environ\.get\(|getenv\()\s*['"](OPENROUTER|DEEPINFRA|ELEVENLABS)_API_KEY"""),
     "reads an AI key"),
    (re.compile(r"^\s*(from openai\b|import openai\b)", re.M), "imports openai"),
]
GATEWAY_CALLS = {"chat", "parse_structured", "transcribe", "ai_transcribe",
                 "http_client", "async_http_client"}


def _python_files():
    for path in API.rglob("*.py"):
        parts = path.relative_to(API).parts
        if parts[0].startswith(".") or "node_modules" in parts or "__pycache__" in parts:
            continue
        yield path


def test_no_module_but_the_gateway_reaches_an_ai_provider():
    offences = []
    for path in _python_files():
        if path.name in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        if path.name.startswith("test_"):   # tests may set fake keys, never call out
            text = re.sub(r"(setdefault|setenv|delenv)\(\s*['\"]\w+_API_KEY.*", "", text)
        for pattern, what in FORBIDDEN:
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                offences.append(f"{path.relative_to(API)}:{line} {what}")
    assert not offences, ("Route these through ai_gateway (see its docstring):\n"
                          + "\n".join(offences))


def test_every_source_named_in_the_code_is_registered():
    named = {}
    for path in _python_files():
        if path.name in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and node.args
                    and getattr(node.func, "id", getattr(node.func, "attr", None)) in GATEWAY_CALLS
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                named[node.args[0].value] = f"{path.relative_to(API)}:{node.lineno}"
    unknown = {s: where for s, where in named.items() if s not in ai_gateway.SOURCES}
    assert not unknown, f"register these in ai_gateway.SOURCES: {unknown}"
    assert set(ai_gateway.SOURCES) <= set(named), (
        f"SOURCES no code uses: {sorted(set(ai_gateway.SOURCES) - set(named))}")


def test_the_spend_table_matches_what_the_ledger_writes():
    sql = (API / "sql" / "ai_spend.sql").read_text()
    row = ai_gateway.Ledger()
    row.add(ai_gateway.Call("tts", "elevenlabs", "m", 200, 1, 0, None, None, 1))
    (written,) = row.take()
    for column in written:
        assert re.search(rf"\b{column}\b", sql), f"ai_spend.sql lacks {column}"
    assert os.environ["AI_SPEND_SINK"] == "log"   # tests never write to Supabase
