"""Transcript selection.

videoparsing imports moviepy and the Whisper client at module scope,
so these tests skip wherever those are not installed rather than failing the
suite. The rule under test is pure enough that the real library objects are
used directly -- no network, and no mock of the thing being verified.
"""

import itertools
import re
from pathlib import Path

import pytest

pytest.importorskip("moviepy")

import videoparsing as vp

TRACK = "https://www.youtube.com/api/timedtext?v=v1&lang={code}&fmt=json3"


def video(manual=(), asr=(), translated=(), video_id="v1"):
    """yt-dlp's info dict, reduced to what caption_track() reads."""
    def formats(code, tlang=None):
        url = TRACK.format(code=code) + (f"&tlang={tlang}" if tlang else "")
        return [{"ext": "vtt", "url": url + "&vtt"}, {"ext": "json3", "url": url}]
    automatic = {c: formats(c) for c in asr}
    automatic.update({c: formats("en", tlang=c) for c in translated})
    return {"id": video_id, "subtitles": {c: formats(c) for c in manual},
            "automatic_captions": automatic}


def chosen(language, **tracks):
    url = vp.caption_track(video(**tracks), language)
    return url and re.search(r"lang=([\w-]+)", url).group(1)


@pytest.mark.parametrize("language,tracks,expected", [
    ("pt", {"asr": ("pt-BR",)}, "pt-BR"),                    # bare code, regional track
    ("en", {"asr": ("en-US",)}, "en-US"),
    ("de", {"asr": ("de-DE", "en")}, "de-DE"),               # the right regional, not the other language
    ("es", {"asr": ("es-419",)}, "es-419"),
    ("es", {"manual": ("es",), "asr": ("es-419", "en")}, "es"),
    ("es", {"manual": ("es-419",), "asr": ("es",)}, "es-419"),  # manual beats ASR
    ("es", {"asr": ("es", "es-orig")}, "es-orig"),           # YouTube's ASR original first
])
def test_tracks_are_matched_on_the_primary_subtag(language, tracks, expected):
    """require_code() always yields a bare ISO 639-1 code, but YouTube publishes
    'pt-BR' and 'en-US' as readily as 'es'."""
    assert chosen(language, **tracks) == expected


def test_a_machine_translated_track_is_never_used():
    """automatic_captions offers an English video translated into every
    language. The Spanish one reads as Spanish, so only its tlang gives it away."""
    assert vp.caption_track(video(asr=("en",), translated=("es",)), "es") is None


def test_no_matching_track_means_whisper():
    assert vp.caption_track(video(asr=("ja", "ko")), "es") is None
    with pytest.raises(vp.NoCaptions):
        vp.fetch_transcript(video(asr=("ja",)), "es", session=object())


def test_json3_cues_become_text_without_sound_tags():
    data = {"events": [{"segs": [{"utf8": "[Música]"}]},
                       {"segs": [{"utf8": "hola"}, {"utf8": " a"}, {"utf8": " todos"}]},
                       {"segs": [{"utf8": "\n"}]},
                       {"tStartMs": 5},
                       {"segs": [{"utf8": "qué  tal"}]}]}
    assert vp.json3_text(data) == "hola a todos qué tal"


def test_one_request_fetches_the_track_and_429_is_a_block():
    class Session:
        def __init__(self, status):
            self.status, self.urls = status, []

        def get(self, url):
            self.urls.append(url)
            return type("R", (), {"status_code": self.status, "raise_for_status": lambda _: None,
                                  "json": lambda _: {"events": [{"segs": [{"utf8": "hola"}]}]}})()

    ok = Session(200)
    assert vp.fetch_transcript(video(asr=("es",)), "es", ok) == "hola"
    assert ok.urls == [TRACK.format(code="es")]
    with pytest.raises(vp.CaptionsBlocked):
        vp.fetch_transcript(video(asr=("es",)), "es", Session(429))


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
    monkeypatch.setattr(vp._ThrottledSession, "_next_at", {False: 0.0, True: 0.0})
    session = vp._ThrottledSession()
    for _ in range(3):
        session.request("GET", "https://www.youtube.com/")
    gaps = [b[0] - a[0] for a, b in itertools.pairwise(sent)]
    assert all(g >= 0.19 for g in gaps)
    assert {t for _, t in sent} == {vp.CAPTION_TIMEOUT_S}


def blocking(calls, failures=99):
    def fetch(info, language, session):
        calls.append((info["id"], session.proxies.get("https")))
        if len(calls) <= failures:
            raise vp.CaptionsBlocked(info["id"])
        return SPANISH
    return fetch


@pytest.fixture
def captions(monkeypatch):
    monkeypatch.setattr(vp, "_captions_blocked_until", {False: 0.0, True: 0.0})
    monkeypatch.setattr(vp, "_proxy_strikes", 0)
    monkeypatch.setattr(vp, "CAPTION_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(vp, "CAPTION_PROXY_INTERVAL_S", 0)
    return monkeypatch


def test_without_a_proxy_a_block_pauses_captions_instead_of_retrying(captions):
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", None)
    captions.setattr(vp, "fetch_transcript", blocking(calls))
    assert vp.caption_text({"id": "v1"}, "es") is None
    assert vp.caption_text({"id": "v2"}, "es") is None
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
    assert vp.caption_text({"id": "v1"}, "es") == SPANISH
    assert len(calls) == 2 and calls[0][1] != calls[1][1]


def test_with_a_proxy_captions_pause_after_repeated_blocked_videos(captions):
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")
    captions.setattr(vp, "fetch_transcript", blocking(calls))
    for vid in ("v1", "v2", "v3", "v4"):
        assert vp.caption_text({"id": vid}, "es") is None
    assert [v for v, _ in calls] == ["v1", "v1", "v2", "v2", "v3", "v3"]   # v4 skipped


def test_a_proxy_that_refuses_pauses_captions(captions):
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")

    def refused(info, language, session):
        calls.append(info["id"])
        raise vp.requests.exceptions.ProxyError("Tunnel connection failed: 407")

    captions.setattr(vp, "fetch_transcript", refused)
    assert vp.caption_text({"id": "v1"}, "es") is None
    assert vp.caption_text({"id": "v2"}, "es") is None
    assert calls == ["v1"]


def test_captions_come_first_and_whisper_only_runs_without_them(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vp, "CAPTION_PROXY_URL", None)      # whatever .env says
    monkeypatch.setattr(vp, "video_info", lambda url, proxied=False: {
        "url": url, "title": "t", "channel": "a", "view_count": 1, "duration": 60})
    processed = []
    monkeypatch.setattr(vp, "process_transcription",
                        lambda f, vid, *a: processed.append(Path(f).read_text()))
    download = []
    monkeypatch.setattr(vp, "download_video", lambda info: download.append(info["url"]))

    monkeypatch.setattr(vp, "caption_text", lambda vid, lang, proxied=None: "hola mundo")
    vp.main("https://www.youtube.com/watch?v=abc", "es")
    assert processed == ["hola mundo"] and download == []

    monkeypatch.setattr(vp, "caption_text", lambda vid, lang, proxied=None: None)
    vp.main("https://www.youtube.com/watch?v=def", "es")
    assert download == ["https://www.youtube.com/watch?v=def"]


def test_ytdlp_calls_are_spaced(monkeypatch):
    now, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s

    monkeypatch.setattr(vp.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(vp.time, "sleep", sleep)
    monkeypatch.setattr(vp, "_ytdlp_next_at", 0.0)
    monkeypatch.setattr(vp, "YTDLP_MIN_INTERVAL_S", 10.0)
    vp._space_ytdlp()
    now[0] += 3
    vp._space_ytdlp()
    assert slept == [7.0]


def test_a_caption_run_reads_metadata_through_the_proxy_and_unspaced(monkeypatch):
    opts = []

    class YDL:
        def __init__(self, o):
            opts.append(o)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def extract_info(self, url, download):
            return {"id": "v1"}

    monkeypatch.setattr(__import__("yt_dlp"), "YoutubeDL", YDL)
    spaced = []
    monkeypatch.setattr(vp, "_space_ytdlp", lambda: spaced.append(1))
    monkeypatch.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")
    vp.video_info("u", proxied=True)
    vp.video_info("u", proxied=True)
    assert opts[0]["proxy"] != opts[1]["proxy"] and "{session}" not in opts[0]["proxy"]
    assert spaced == []
    vp.video_info("u")                                   # our own IP: spaced, no proxy
    assert "proxy" not in opts[2] and spaced == [1]


def test_a_failed_download_from_proxied_info_rereads_on_our_own_ip(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")
    reads = []
    monkeypatch.setattr(vp, "video_info", lambda url, proxied=False: (
        reads.append(proxied), {"url": url, "proxied": proxied})[1])
    monkeypatch.setattr(vp, "caption_text", lambda info, lang, proxied=None: None)
    downloads = []
    monkeypatch.setattr(vp, "download_video",
                        lambda info: (downloads.append(info["proxied"]), None)[1])
    vp.main("https://www.youtube.com/watch?v=abc", "es")
    assert reads == [True, False] and downloads == [True, False]


def test_own_ip_and_proxy_captions_are_spaced_and_paused_separately(captions):
    """An ingest mix fetches captions both ways at once. A block on our own IP
    must not stop the proxy, and the proxy's 0.5 s spacing must not apply to
    our own IP."""
    calls = []
    captions.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")

    def fetch(info, language, session):
        calls.append((info["id"], session.proxied))
        if not session.proxied:
            raise vp.CaptionsBlocked(info["id"])
        return SPANISH

    captions.setattr(vp, "fetch_transcript", fetch)
    assert vp.caption_text({"id": "own1"}, "es", proxied=False) is None
    assert vp.caption_text({"id": "own2"}, "es", proxied=False) is None      # paused
    assert vp.caption_text({"id": "px1"}, "es", proxied=True) == SPANISH
    assert calls == [("own1", False), ("px1", True)]
    assert vp.caption_session(False).proxies == {} and vp.caption_session(True).proxies


def test_use_proxy_false_keeps_a_caption_video_on_our_own_ip(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(vp, "CAPTION_PROXY_URL", "http://user-x-session-{session}:pw@proxy:1")
    seen = []
    monkeypatch.setattr(vp, "video_info", lambda url, proxied=False: (
        seen.append(("read", proxied)), {"url": url})[1])
    monkeypatch.setattr(vp, "caption_text", lambda info, lang, proxied=None: (
        seen.append(("captions", proxied)), "hola")[1])
    monkeypatch.setattr(vp, "process_transcription", lambda *a: None)
    vp.main("https://www.youtube.com/watch?v=abc", "es", use_proxy=False)
    vp.main("https://www.youtube.com/watch?v=def", "es")
    assert seen == [("read", False), ("captions", False), ("read", True), ("captions", True)]
