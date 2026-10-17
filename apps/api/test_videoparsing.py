"""Transcript selection.

videoparsing imports moviepy, pytubefix and the Whisper client at module scope,
so these tests skip wherever those are not installed rather than failing the
suite. The rule under test is pure enough that the real library objects are
used directly -- no network, and no mock of the thing being verified.
"""

import itertools
from pathlib import Path

import pytest

pytest.importorskip("youtube_transcript_api")
pytest.importorskip("moviepy")

from youtube_transcript_api import NoTranscriptFound
from youtube_transcript_api._transcripts import Transcript, TranscriptList

import videoparsing as vp


def track_list(manual=(), generated=(), video_id="v1"):
    def build(code, gen):
        return Transcript(None, video_id, "url", code, code, gen, [])
    return TranscriptList(video_id,
                          {c: build(c, False) for c in manual},
                          {c: build(c, True) for c in generated}, {})


def chosen(language, manual=(), generated=()):
    """The track fetch_transcript would pick, without fetching it."""
    tracks = track_list(manual, generated)
    original = vp.YouTubeTranscriptApi.list
    try:
        vp.YouTubeTranscriptApi.list = lambda _self, _vid: tracks
        picked = {}
        for transcript in tracks:
            transcript.fetch = lambda t=transcript: picked.setdefault("code", t.language_code)
        vp.fetch_transcript("v1", language)
        return picked.get("code")
    finally:
        vp.YouTubeTranscriptApi.list = original


@pytest.mark.parametrize("language,manual,generated,expected", [
    ("pt", (), ("pt-BR",), "pt-BR"),          # the bug: bare code, regional track
    ("en", (), ("en-US",), "en-US"),
    ("de", (), ("de-DE", "en"), "de-DE"),     # the right regional, not the other language
    ("es", (), ("es-419",), "es-419"),
    ("es", ("es",), ("es-419", "en"), "es"),  # exact code beats a regional variant
    ("es", ("es",), ("es",), "es"),           # manual beats ASR
])
def test_regional_caption_tracks_are_matched_on_the_primary_subtag(
        language, manual, generated, expected):
    """require_code() always yields a bare ISO 639-1 code, but YouTube publishes
    'pt-BR' and 'en-US' as readily as 'es'. The library compares the two with an
    exact dict lookup -- still true in 1.2.4 -- so every regional track was
    invisible and the video looked as though it had no captions."""
    assert chosen(language, manual, generated) == expected


def test_no_matching_track_raises_so_main_can_fall_back_to_whisper():
    with pytest.raises(NoTranscriptFound):
        chosen("es", generated=("ja", "ko"))


def test_the_old_exact_match_really_did_miss_regional_tracks():
    """Pins the bug itself, so a future revert cannot pass silently."""
    with pytest.raises(NoTranscriptFound):
        track_list(generated=("pt-BR",)).find_transcript(["pt"])


# ═════════════════════════════════ a track's label is a claim, not a guarantee ══

SPANISH = ("Hoy vamos a explicar cómo funciona el sistema solar y por qué los "
           "planetas giran alrededor del sol. Es una historia larga que empieza "
           "hace muchos millones de años, cuando una nube de gas y polvo "
           "comenzó a colapsar sobre sí misma por efecto de la gravedad. ") * 2
CATALAN = ("Perdó, ja vaig agafar un altre avió cap a casa meva perquè no "
           "volia esperar més temps a l'aeroport amb tota aquella gent que "
           "esperava el mateix vol que jo aquella nit tan freda de desembre. ") * 3


def test_a_track_whose_text_is_another_language_is_rejected():
    """A real video publishes a 'pt-BR' track whose text is Catalan, identical
    to its own 'ca' track. Nothing in the matching can see that -- the label is
    wrong in YouTube's data -- so the text itself is checked."""
    assert not videoparsing_matches(CATALAN, "pt")


def test_the_right_language_passes():
    assert videoparsing_matches(SPANISH, "es")


def test_short_or_unreadable_text_is_not_rejected():
    """Abstain rather than reject: a false rejection costs a Whisper run, but
    the check exists to stop poisoning, not to gate ingestion."""
    assert videoparsing_matches("[Música] [Música] gracias", "es")
    assert videoparsing_matches("", "fr")


def videoparsing_matches(text, language):
    return vp.transcript_language_matches(text, language)


# ═══════════════════════════════════ Whisper on pieces cut at the quiet points ══

def test_pieces_end_at_the_quietest_moment_and_stay_under_the_window():
    import itertools

    import numpy as np
    energy = np.ones(int(100 / vp.FRAME_S))
    energy[int(21.0 / vp.FRAME_S)] = 0.0             # a pause 21 s in
    spans = vp.pieces(energy, 100.0)
    assert spans[0] == (0.0, pytest.approx(21.0))
    assert all(end - start <= vp.PIECE_MAX_S for start, end in spans)
    assert spans[-1][1] == 100.0
    assert all(a[1] == b[0] for a, b in itertools.pairwise(spans))   # nothing between pieces


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_a_piece_far_below_speaking_rate_is_split_and_retried(tmp_path):
    """Whisper sometimes skips most of a piece. The retry splits it in two and
    keeps whichever reading has more words."""
    import os
    import wave

    import numpy as np
    audio = tmp_path / "a.wav"
    rate = 16000
    t = np.arange(40 * rate) / rate
    tone = (3000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)
    tone[int(20 * rate):int(20.5 * rate)] = 0            # one pause, so two pieces
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(tone.tobytes())

    def fake_whisper(path, language):
        import subprocess
        seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                        "-of", "csv=p=0", path], capture_output=True, text=True).stdout)
        if seconds > 15:                                 # the first, whole-piece pass
            return "solo dos" if os.path.basename(path).startswith("00000.000-") else "palabra " * 50
        return "palabra " * 30                          # each half of the retry

    text = vp.transcribe_in_pieces(str(audio), "es", transcribe=fake_whisper)
    assert len(text.split()) == 30 + 30 + 50


# ═════════════════════════════════════ captions first, throttled, Whisper as backup ══

def test_caption_requests_are_spaced_and_time_out(monkeypatch):
    sent = []
    monkeypatch.setattr(vp.requests.Session, "request",
                        lambda self, *a, **k: sent.append((vp.time.monotonic(), k["timeout"])))
    monkeypatch.setattr(vp, "CAPTION_MIN_INTERVAL_S", 0.2)
    monkeypatch.setattr(vp._ThrottledSession, "_next_at", 0.0)
    session = vp._ThrottledSession()
    for _ in range(3):
        session.request("GET", "https://www.youtube.com/")
    gaps = [b[0] - a[0] for a, b in itertools.pairwise(sent)]
    assert all(g >= 0.19 for g in gaps)
    assert {t for _, t in sent} == {vp.CAPTION_TIMEOUT_S}


def blocking(calls, failures=99):
    def fetch(video_id, language, session):
        calls.append((video_id, session.proxies.get("https")))
        if len(calls) <= failures:
            raise vp.RequestBlocked(video_id)
        return [type("S", (), {"text": SPANISH})()]
    return fetch


@pytest.fixture
def captions(monkeypatch):
    monkeypatch.setattr(vp, "_captions_blocked_until", 0.0)
    monkeypatch.setattr(vp, "_proxy_strikes", 0)
    monkeypatch.setattr(vp, "CAPTION_MIN_INTERVAL_S", 0)
    return monkeypatch


def test_without_a_proxy_a_block_pauses_captions_instead_of_retrying(captions):
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", None)
    captions.setattr(vp, "fetch_transcript", blocking(calls))
    assert vp.caption_text("v1", "es") is None
    assert vp.caption_text("v2", "es") is None
    assert [v for v, _ in calls] == ["v1"]          # v2 never asked YouTube


def test_each_video_gets_its_own_proxy_session_and_cookies(captions):
    captions.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")
    a, b = vp.caption_session(), vp.caption_session()
    assert a is not b and a.cookies is not b.cookies
    assert a.proxies["https"] != b.proxies["https"]
    assert "{session}" not in a.proxies["https"] and a.proxies["https"] == a.proxies["http"]


def test_with_a_proxy_a_blocked_video_is_retried_once_on_a_new_ip(captions):
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")
    captions.setattr(vp, "fetch_transcript", blocking(calls, failures=1))
    assert vp.caption_text("v1", "es") == SPANISH
    assert len(calls) == 2 and calls[0][1] != calls[1][1]


def test_with_a_proxy_captions_pause_after_repeated_blocked_videos(captions):
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")
    captions.setattr(vp, "fetch_transcript", blocking(calls))
    for vid in ("v1", "v2", "v3", "v4"):
        assert vp.caption_text(vid, "es") is None
    assert [v for v, _ in calls] == ["v1", "v1", "v2", "v2", "v3", "v3"]   # v4 skipped


def test_a_proxy_that_refuses_pauses_captions(captions):
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")

    def refused(video_id, language, session):
        calls.append(video_id)
        raise vp.requests.exceptions.ProxyError("Tunnel connection failed: 407")

    captions.setattr(vp, "fetch_transcript", refused)
    assert vp.caption_text("v1", "es") is None
    assert vp.caption_text("v2", "es") is None
    assert calls == ["v1"]


def test_captions_come_first_and_whisper_only_runs_without_them(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vp.pytube, "YouTube", lambda url, client: type("YT", (), {
        "title": "t", "author": "a", "keywords": [], "views": 1, "length": 60})())
    processed = []
    monkeypatch.setattr(vp, "process_transcription",
                        lambda f, vid, *a: processed.append(Path(f).read_text()))
    download = []
    monkeypatch.setattr(vp, "download_video", lambda url: download.append(url))

    monkeypatch.setattr(vp, "caption_text", lambda vid, lang: "hola mundo")
    vp.main("https://www.youtube.com/watch?v=abc", "es")
    assert processed == ["hola mundo"] and download == []

    monkeypatch.setattr(vp, "caption_text", lambda vid, lang: None)
    vp.main("https://www.youtube.com/watch?v=def", "es")
    assert download == ["https://www.youtube.com/watch?v=def"]
