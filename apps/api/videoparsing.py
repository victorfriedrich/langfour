import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime

import pytubefix as pytube
import requests
from dotenv import load_dotenv
from moviepy.editor import VideoFileClip
from youtube_transcript_api import (
    NoTranscriptFound,
    RequestBlocked,
    YouTubeRequestFailed,
    YouTubeTranscriptApi,
)

from languages import require_code
from llm_client import transcription_client
from models import MODEL_TRANSCRIBE
from nlp_processing import get_tags, group_text, parse
from paths import processed_file

load_dotenv()

# Whisper runs on DeepInfra: OpenRouter has no /audio/transcriptions
# endpoint. The client is built lazily inside the function, so importing
# this module does not require a DeepInfra key.

def download_video(url):
    """The audio track only, as the file yt-dlp wrote. pytubefix's ANDROID
    client started failing every download with HTTP 400; its metadata calls
    in main() still work, so only the download moved."""
    import yt_dlp
    try:
        start_time = time.time()
        with yt_dlp.YoutubeDL({"format": "bestaudio[ext=m4a]/bestaudio",
                               "outtmpl": "%(id)s.%(ext)s", "quiet": True,
                               "no_warnings": True, "noprogress": True}) as ydl:
            audio_file = ydl.prepare_filename(ydl.extract_info(url, download=True))
        print(f"Audio downloaded in {time.time() - start_time:.2f} seconds")
        return audio_file
    except Exception as e:
        print(f"Error occurred during video download: {e}")
        return None

def convert_to_mp3(filename):
    try:
        start_time = time.time()
        clip = VideoFileClip(filename)
        mp3_filename = filename[:-4] + ".mp3"
        clip.audio.write_audiofile(mp3_filename)
        clip.close()
        end_time = time.time()
        print(f"MP3 conversion completed in {end_time - start_time:.2f} seconds")
        return mp3_filename
    except Exception as e:
        print(f"Error converting to MP3: {e}")
        return None

# Whisper reads 30 seconds of audio at a time, and DeepInfra cuts a long file
# into fixed 30-second windows. Whisper often stops a window early, and the
# next one starts at the fixed boundary, so the end of a window is lost: on
# test videos 6-12% of the words, whole sentences at a time. Sending pieces
# shorter than 30 seconds, cut where the audio is quietest, keeps every piece
# inside one window. A piece that still comes back far below speaking rate had
# speech skipped anyway, and is split once more and retried.
FRAME_S = 0.02                 # energy is measured per 20 ms
PIECE_MIN_S, PIECE_MAX_S = 15.0, 28.0
MIN_WORDS_PER_SECOND = 1.0     # normal speech is 2-3


def frame_energy(audio_file: str):
    """Loudness per FRAME_S, smoothed over ~300 ms so a cut lands in a pause
    between words rather than in a one-frame dip inside one."""
    import subprocess

    import numpy as np
    rate = 16000
    pcm = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", audio_file,
                          "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    samples = np.frombuffer(pcm, np.int16).astype(np.float32)
    hop = int(FRAME_S * rate)
    frames = samples[: len(samples) // hop * hop].reshape(-1, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return np.convolve(rms, np.ones(15) / 15, mode="same"), len(samples) / rate


def quietest(energy, start: float, end: float) -> float:
    i, j = int(start / FRAME_S), max(int(start / FRAME_S) + 1, int(end / FRAME_S))
    return (i + int(energy[i:j].argmin())) * FRAME_S


def pieces(energy, duration: float) -> list[tuple[float, float]]:
    """(start, end) spans of PIECE_MIN_S..PIECE_MAX_S, each ending at the
    quietest moment its window allows."""
    cuts = [0.0]
    while duration - cuts[-1] > PIECE_MAX_S:
        cuts.append(quietest(energy, cuts[-1] + PIECE_MIN_S, cuts[-1] + PIECE_MAX_S))
    return list(zip(cuts, [*cuts[1:], duration], strict=True))


def whisper(audio_file: str, language: str) -> str:
    """One transcription request, retried briefly: DeepInfra answers 429 when
    busy even under its concurrency limit."""
    for attempt in range(3):
        try:
            with open(audio_file, "rb") as fh:
                result = transcription_client().audio.transcriptions.create(
                    model=MODEL_TRANSCRIBE, file=fh, response_format="text", language=language)
            # A bare string on OpenAI; DeepInfra may return an object instead.
            return (result if isinstance(result, str) else result.text).strip()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return ""


def transcribe_in_pieces(audio_file: str, language: str, transcribe=whisper) -> str:
    """The whole file's text, transcribed as pieces all sent at once."""
    import subprocess
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    energy, duration = frame_energy(audio_file)
    spans = pieces(energy, duration)
    with tempfile.TemporaryDirectory() as tmp:
        def piece(span):
            start, end = span
            path = os.path.join(tmp, f"{start:09.3f}-{end:09.3f}.m4a")   # a retry half shares the start
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", audio_file,
                            "-c:a", "aac", "-b:a", "96k", path], check=True)
            return transcribe(path, language)

        with ThreadPoolExecutor(max_workers=64) as pool:   # DeepInfra allows 200
            texts = list(pool.map(piece, spans))
        for i, ((start, end), text) in enumerate(zip(spans, texts, strict=True)):
            if len(text.split()) < (end - start) * MIN_WORDS_PER_SECOND:
                middle = quietest(energy, start + (end - start) * 0.3, start + (end - start) * 0.7)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    retry = " ".join(pool.map(piece, [(start, middle), (middle, end)]))
                if len(retry.split()) > len(text.split()):
                    texts[i] = retry
    return " ".join(t for t in texts if t)


def transcribe_audio(mp3_filename, video_id, language):
    # Ensure the 'transcripts' directory exists
    os.makedirs("transcripts", exist_ok=True)
    
    txt_filename = os.path.join("transcripts", f"{video_id}.txt")
    if os.path.exists(txt_filename):
        print(f"Transcription file {txt_filename} already exists. Skipping transcription.")
        return txt_filename
    
    try:
        start_time = time.time()
        text = transcribe_in_pieces(mp3_filename, language)
        with open(txt_filename, "w", encoding='utf-8') as txt_file:
            txt_file.write(text)
        end_time = time.time()
        print(f"Audio transcription completed in {end_time - start_time:.2f} seconds")
        return txt_filename
    except Exception as e:
        print(f"Error during transcription: {e}")
        return None
    finally:
        cleanup_files(mp3_filename)

def cleanup_files(*filenames):
    for filename in filenames:
        try:
            if os.path.exists(filename):
                os.remove(filename)
                print(f"Deleted file: {filename}")
        except Exception as e:
            print(f"Error deleting file {filename}: {e}")

# A caption track's label is a claim, not a guarantee. One video in the corpus
# publishes a track tagged 'pt-BR' whose text is byte-identical to its Catalan
# track -- a creator uploading the wrong file. No amount of code-matching can
# see that, because the mislabelling is in YouTube's own data, so the text is
# checked after it is fetched. A Catalan transcript filed under Portuguese is
# exactly the kind of thing a language-learning corpus must not absorb.
MIN_TRANSCRIPT_CHARS = 200


def transcript_language_matches(text: str, language: str) -> bool:
    """False only when the detector is confident the text is another language.

    Abstains on short or unreadable text rather than rejecting it: the cost of
    a false rejection is a Whisper run, but the cost of a false acceptance is a
    permanently poisoned pool, and most transcripts are neither."""
    global _DETECTOR
    try:
        # Reused from ytpipeline rather than restated, so the transcript check
        # and channel detection cannot drift apart on thresholds or noise rules.
        from ytpipeline import DETECT_LANGS, MIN_CONF, clean
        body = clean(text)
        if len(body) < MIN_TRANSCRIPT_CHARS:
            return True
        from lingua import Language, LanguageDetectorBuilder
        if _DETECTOR is None:
            _DETECTOR = (LanguageDetectorBuilder
                         .from_languages(*[getattr(Language, n) for n in DETECT_LANGS])
                         .with_preloaded_language_models().build())
    except ImportError:
        # Fail open. This is a guard against bad upstream data, not a gate on
        # ingestion: a deployment without lingua should still build a corpus.
        return True
    values = _DETECTOR.compute_language_confidence_values(body[:4000])
    if not values or values[0].value < MIN_CONF:
        return True
    return values[0].language.iso_code_639_1.name.lower() == language.lower()


_DETECTOR = None


# YouTube blocks an IP's caption requests after a burst: on 2026-10-17 about 40
# requests in three minutes got this machine IpBlocked, and the block covered
# yt-dlp's subtitle downloads too (HTTP 429) and still held a day later. So:
#
# - CAPTION_PROXY_URL (optional) sends caption requests through a rotating
#   residential proxy. A "{session}" in it is replaced per video, which for
#   Decodo-style usernames (user-NAME-session-{session}-sessionduration-1)
#   keeps one video's three requests (watch page, player, track) on one IP and
#   moves the next video to another. Each video also gets a fresh Session, so
#   no cookie or visitor id links the IPs together.
# - Requests are spaced CAPTION_MIN_INTERVAL_S apart: 10 s on our own IP, 0.5 s
#   (a second or two per video) when the proxy spreads them over many IPs.
#   They also time out: the library sets no timeout, and one stalled request
#   hung a run for ten minutes.
# - A blocked video is retried once on a new proxy session. Without a proxy, or
#   after CAPTION_PROXY_STRIKES blocked videos in a row, or when the proxy
#   itself refuses (out of traffic: 407), captions pause for CAPTION_COOLDOWN_S
#   and videos go straight to Whisper instead of extending the block.
CAPTION_PROXY_URL = os.getenv("CAPTION_PROXY_URL") or None
CAPTION_MIN_INTERVAL_S = float(os.getenv("CAPTION_MIN_INTERVAL_S",
                                         "0.5" if CAPTION_PROXY_URL else "10"))
CAPTION_COOLDOWN_S = float(os.getenv("CAPTION_COOLDOWN_S", "3600"))
CAPTION_PROXY_STRIKES = 3
CAPTION_TIMEOUT_S = 15


class _ThrottledSession(requests.Session):
    """Spaces every caption request, across all sessions, CAPTION_MIN_INTERVAL_S apart."""
    _lock = threading.Lock()
    _next_at = 0.0

    def request(self, *args, **kwargs):
        with self._lock:
            wait = _ThrottledSession._next_at - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _ThrottledSession._next_at = time.monotonic() + CAPTION_MIN_INTERVAL_S
        kwargs.setdefault("timeout", CAPTION_TIMEOUT_S)
        return super().request(*args, **kwargs)


def caption_session() -> requests.Session:
    """A fresh session (no cookies) for one video, on its own proxy session."""
    session = _ThrottledSession()
    if CAPTION_PROXY_URL:
        url = CAPTION_PROXY_URL.replace("{session}", uuid.uuid4().hex[:12])
        session.proxies = {"http": url, "https": url}
    return session


_captions_blocked_until = 0.0
_proxy_strikes = 0


def _is_block(exc: Exception) -> bool:
    return isinstance(exc, RequestBlocked) or (
        isinstance(exc, YouTubeRequestFailed) and "429" in str(exc))


def _pause_captions(reason: str) -> None:
    global _captions_blocked_until
    _captions_blocked_until = time.monotonic() + CAPTION_COOLDOWN_S
    print(f"{reason}; using Whisper only for the next {CAPTION_COOLDOWN_S / 60:.0f} min")


def caption_text(video_id: str, language: str) -> str | None:
    """The video's caption text, or None when there is no usable track, the
    track reads as another language, or YouTube is blocking caption requests."""
    global _proxy_strikes
    if time.monotonic() < _captions_blocked_until:
        return None
    attempts = 2 if CAPTION_PROXY_URL else 1
    for attempt in range(attempts):
        try:
            start_time = time.time()
            transcript = fetch_transcript(video_id, language, caption_session())
            print(f"Transcript fetched in {time.time() - start_time:.2f} seconds")
            _proxy_strikes = 0
            break
        except requests.exceptions.ProxyError as e:
            reason = str(e).rsplit("failed: ", 1)[-1].split("'")[0][:80]
            _pause_captions(f"The caption proxy refused the request ({reason})")
            return None
        except Exception as e:
            if _is_block(e) and attempt + 1 < attempts:
                print(f"Caption request for {video_id} blocked; retrying on a new IP")
                continue
            if _is_block(e):
                _proxy_strikes += 1
                if not CAPTION_PROXY_URL or _proxy_strikes >= CAPTION_PROXY_STRIKES:
                    _pause_captions(f"YouTube is blocking caption requests ({type(e).__name__})")
                return None
            # Deliberately any failure, not just the library's typed ones:
            # youtube_transcript_api is a scraper, and a scraper's failure mode is
            # not always a tidy exception (0.6.2 died in xml.etree with ParseError).
            print(f"No usable '{language}' captions for {video_id} "
                  f"({type(e).__name__}: {(str(e).splitlines() or [''])[0][:120]})")
            return None

    # TODO: Localize based on language
    # Música
    # 1.x yields FetchedTranscriptSnippet objects, not dicts.
    text = ' '.join(snippet.text for snippet in transcript if snippet.text != '[Musik]')
    if not transcript_language_matches(text, language):
        print(f"Caption track for {video_id} is labelled '{language}' but reads as "
              f"another language; not using it")
        return None
    return text


def fetch_transcript(video_id: str, language: str, session: requests.Session | None = None):
    """Caption cues for `language`, matched on the primary subtag.

    YouTube's track codes are inconsistent -- bare 'es' on one video, 'pt-BR',
    'en-US' or 'de-DE' on the next -- while `language` is always a bare ISO
    639-1 code, because require_code() normalises it. The library compares the
    two with `in`, an exact dict-key lookup (still true in 1.2.4), so asking for
    ['pt'] cannot match a track published as 'pt-BR' and the video is reported
    as having no captions at all. Spanish publishes bare 'es' and hid this;
    Portuguese and English do not.

    Raises NoTranscriptFound when nothing matches, which main() now treats as a
    reason to transcribe the audio rather than as the end of the video.
    """
    # 1.x is instance-based; list_transcripts/get_transcript no longer exist.
    # The upgrade off 0.6.2 was not cosmetic: that version still listed a
    # video's caption tracks but its timedtext fetch returned an empty body
    # against current YouTube, so every fetch died in xml.etree with ParseError.
    # Measured on real videos: 0/7 fetched on 0.6.2, 4/7 on 1.2.4 -- the other
    # three being genuine TranscriptsDisabled, which Whisper now picks up.
    available = YouTubeTranscriptApi(http_client=session or caption_session()).list(video_id)
    codes = [t.language_code for t in available]
    target = language.lower()
    matching = [c for c in codes if c.split('-')[0].lower() == target]
    if not matching:
        raise NoTranscriptFound(video_id, [language], available)
    # Exact code first, then regional variants in the order YouTube listed them.
    # find_transcript itself prefers a manually created track over an ASR one.
    matching.sort(key=lambda c: (c.lower() != target, codes.index(c)))
    return available.find_transcript(matching).fetch()


def main(url, language: str, use_transcript_api=True):
    
    # Was an if/elif ending in an unguarded `else: 'de'`, so an ISO code
    # (what every client now sends) silently routed the transcript into the
    # German directory. Normalised into `language` itself rather than a second
    # variable: the two were the same value from here on, and keeping both in
    # scope is how the wrong one gets picked up later.
    language = require_code(language)
    
    # split('&')[0] too: a watch URL often carries more than v=, and keeping
    # the tail produced 46 transcripts named '<id>&pp=0gcJ..._processed.json'.
    # The recommender derives the video id from the filename, so that junk was
    # served straight to clients.
    video_id = url.split('v=')[-1].split('&')[0]

    # Ensure the 'transcripts' directory exists
    os.makedirs("transcripts", exist_ok=True)
    
    txt_filename = os.path.join("transcripts", f"{video_id}.txt")
    
    # Initialize YouTube object to extract metadata
    try:
        yt = pytube.YouTube(url, 'WEB')
        title = yt.title
        creator = yt.author
        tags = yt.keywords
        views = yt.views
        length = yt.length  # Duration in seconds
        date_added = datetime.utcnow().isoformat()  # UTC timestamp
    except Exception as e:
        print(f"Error extracting metadata for video {video_id}: {e}")
        traceback.print_exc()
        return

    if os.path.exists(txt_filename):
        print(f"Transcription file {txt_filename} already exists. Processing...")
        process_transcription(txt_filename, video_id, title, creator, tags, views, length, date_added, language)
        return

    # Captions first, Whisper when there are none. Captions take ~2 s and cost
    # nothing; Whisper needs the audio download plus 15-60 s of DeepInfra per
    # video. Manual tracks are punctuated, ASR tracks mostly are not, which
    # parse() doesn't need.
    if use_transcript_api:
        text = caption_text(video_id, language)
        if text:
            with open(txt_filename, "w", encoding='utf-8') as txt_file:
                txt_file.write(text)
            process_transcription(txt_filename, video_id, title, creator, tags, views, length, date_added, language)
            return

    audio_file = download_video(url)
    if not audio_file:
        print(f"Audio download failed for {video_id}")
        return
    transcription_file = transcribe_audio(audio_file, video_id, language)
    cleanup_files(audio_file)
    if transcription_file:
        print(f"Transcription saved as: {transcription_file}")
        process_transcription(transcription_file, video_id, title, creator, tags, views, length, date_added, language)
    else:
        print(f"Audio transcription failed for {video_id}")

def process_transcription(txt_filename, video_id, title, creator, tags, views, length, date_added, language):
    try:
        start_time = time.time()
        with open(txt_filename, encoding='utf-8') as file:
            transcription_text = file.read()

        # This takes too long
        filtered_text = transcription_text
        # filtered_text = filter_entities(transcription_text, language)
        alternative_tags = get_tags(title, transcription_text)
        print(f"Keywords: {alternative_tags}")
        
        groups = group_text(filtered_text)
        content = parse(groups, video_id, language)


        # Prepare the complete metadata dictionary
        result = {
            "title": title,
            "id": video_id,
            "tags": list(set(tags + alternative_tags)),
            "creator": creator,
            "views": views,
            "length": length,
            "content": content,
            "dateAdded": date_added
        }

        language = require_code(language)

        # Ensure the 'processed' directory exists
        _out = processed_file(language, video_id)
        _out.parent.mkdir(parents=True, exist_ok=True)
        with open(_out, "w", encoding='utf-8') as json_file:
            json.dump(result, json_file, ensure_ascii=False, indent=4)

        end_time = time.time()
        print(f"Transcription processing completed in {end_time - start_time:.2f} seconds")
    except Exception as e:
        traceback.print_exc()
        raise Exception(f"Error in processing transcript: {e!s}") from e