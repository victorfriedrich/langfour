"""Transcript selection.

videoparsing imports moviepy, pytubefix and the Whisper client at module scope,
so these tests skip wherever those are not installed rather than failing the
suite. The rule under test is pure enough that the real library objects are
used directly -- no network, and no mock of the thing being verified.
"""

import pytest

pytest.importorskip("youtube_transcript_api")
pytest.importorskip("moviepy")

from youtube_transcript_api import NoTranscriptFound
from youtube_transcript_api._transcripts import Transcript, TranscriptList

import videoparsing as vp


def track_list(manual=(), generated=(), video_id="v1"):
    build = lambda code, gen: Transcript(None, video_id, "url", code, code, gen, [])
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
