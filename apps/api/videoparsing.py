import json
import os
import re
import threading
import time
import traceback
import urllib.parse
import uuid
from datetime import datetime

import requests
from dotenv import load_dotenv
from moviepy.editor import VideoFileClip

from languages import require_code
from llm_client import transcription_client
from models import MODEL_TRANSCRIBE
from nlp_processing import group_text, parse
from paths import processed_file

load_dotenv()

# Whisper runs on DeepInfra: OpenRouter has no /audio/transcriptions
# endpoint. The client is built lazily inside the function, so importing
# this module does not require a DeepInfra key.

# Every YouTube request from here goes through yt-dlp, once per video: the
# metadata read in main() also selects the audio format, so a Whisper fallback
# downloads from that same info without loading the page again. (pytubefix
# used to read the metadata, which cost a second page load for the same
# fields.)
#
# The smallest audio track, in the video's original language: Whisper hears
# 16 kHz mono, so opus at ~50 kbps (format 249) is 40% of the bytes of the
# ~130 kbps m4a that "bestaudio" picks. On a 6-minute Spanish video the two
# transcripts shared 98.8% of their words (two runs on the m4a: 99.9%), with
# the same word count. "+abr" makes the lowest bitrate the best; "lang" first
# keeps a dubbed track from winning on size.
YDL_OPTS = {"format": "ba[acodec=opus]/ba", "format_sort": ["lang", "+abr"],
            "outtmpl": "%(id)s.%(ext)s", "quiet": True, "no_warnings": True,
            "noprogress": True}
# yt-dlp's wiki asks for 5-10 s between videos on one IP. With CAPTION_PROXY_URL
# set, a caption run reads each video's metadata through its own proxy session
# (a new IP per video), so only reads from our own IP are spaced: Whisper-only
# runs, and the re-read when a download from proxied info fails.
YTDLP_MIN_INTERVAL_S = float(os.getenv("YTDLP_MIN_INTERVAL_S", "10"))
_ytdlp_lock = threading.Lock()
_ytdlp_next_at = 0.0


def _space_ytdlp() -> None:
    global _ytdlp_next_at
    with _ytdlp_lock:
        wait = _ytdlp_next_at - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _ytdlp_next_at = time.monotonic() + YTDLP_MIN_INTERVAL_S


def video_info(url, proxied: bool = False, proxy: str | None = None) -> dict:
    """Metadata and the selected audio format, from one page load.

    proxied=True sends the read through `proxy` (a proxy_url() session),
    or a fresh one, when CAPTION_PROXY_URL is set: ~1.8 MB of proxy traffic and 3-4 s per video
    (measured on three videos), against a limit of roughly 300 videos an hour
    for one signed-out IP. Audio downloads never use the proxy: ~2-5 MB each
    is too much traffic to pay for, and the googlevideo URL a proxied read
    returns still downloaded from our own IP."""
    import yt_dlp
    opts = dict(YDL_OPTS)
    if proxied and CAPTION_PROXY_URL:
        opts["proxy"] = proxy or proxy_url()
    else:
        _space_ytdlp()
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _proxy_turned_away(exc: Exception) -> bool:
    """YouTube's bot check, or the proxy failing to connect: worth one more
    try on a new IP. A shared residential IP can arrive already flagged."""
    text = str(exc).lower()
    return "confirm you" in text or "not a bot" in text or "proxy" in text


def read_info(url: str, proxied: bool) -> tuple[dict, str | None]:
    """video_info() and the proxy session it used, so the video's caption
    request can come from the same IP. A proxied read YouTube turns away is
    retried once on a new session; a read on our own IP is not retried."""
    session = proxy_url() if proxied else None
    try:
        return video_info(url, proxied=proxied, proxy=session), session
    except Exception as exc:
        if not proxied or not _proxy_turned_away(exc):
            raise
        print(f"Metadata read turned away on the proxy "
              f"({(str(exc).splitlines() or [''])[0][:90]}); retrying on a new IP")
        session = proxy_url()
        return video_info(url, proxied=True, proxy=session), session


def download_video(info):
    """The audio track video_info() selected, as the file yt-dlp wrote."""
    import yt_dlp
    try:
        start_time = time.time()
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            ydl.process_info(info)
            audio_file = ydl.prepare_filename(info)
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
# requests in three minutes got this machine IpBlocked, and on 2026-10-29 about
# 36 in seven minutes did it again despite 10 s spacing -- so the limit counts
# requests, not just their rate. The track is therefore fetched straight from
# the URL yt-dlp's metadata read already returned: one request per video, where
# youtube_transcript_api made three (watch page, player, track) on top of it.
#
# - CAPTION_PROXY_URL (optional) sends the track request through a rotating
#   residential proxy. A "{session}" in it is replaced per video, and each
#   video gets a fresh Session, so nothing links one video's IP to the next.
#   The track URLs are signed with ipbits=0, so a URL read on our own IP still
#   works from the proxy's.
# - Requests are spaced CAPTION_MIN_INTERVAL_S apart: 10 s on our own IP, 0.5 s
#   when the proxy spreads them over many IPs. They also time out.
# - A blocked video (HTTP 429) is retried once on a new proxy session. Without
#   a proxy, or after CAPTION_PROXY_STRIKES blocked videos in a row, or when
#   the proxy itself refuses (out of traffic: 407), captions pause for
#   CAPTION_COOLDOWN_S and videos go straight to Whisper instead of extending
#   the block.
CAPTION_PROXY_URL = os.getenv("CAPTION_PROXY_URL") or None
# Caption requests from our own IP and through the proxy are spaced, and
# paused after a block, separately: an ingest mix can use both routes at once.
CAPTION_MIN_INTERVAL_S = float(os.getenv("CAPTION_MIN_INTERVAL_S", "10"))
CAPTION_PROXY_INTERVAL_S = float(os.getenv("CAPTION_PROXY_INTERVAL_S", "0.5"))
CAPTION_COOLDOWN_S = float(os.getenv("CAPTION_COOLDOWN_S", "3600"))
CAPTION_PROXY_STRIKES = 3
CAPTION_TIMEOUT_S = 15


class NoCaptions(Exception):
    """The video has no usable track in the language."""


class CaptionsBlocked(Exception):
    """YouTube answered the track request with 429."""


class _ThrottledSession(requests.Session):
    """Spaces every caption request on one route (our IP, or the proxy), across
    all sessions, CAPTION_MIN_INTERVAL_S or CAPTION_PROXY_INTERVAL_S apart."""
    _lock = threading.Lock()
    _next_at = {False: 0.0, True: 0.0}

    def __init__(self, proxied: bool = False):
        super().__init__()
        self.proxied = proxied

    def request(self, *args, **kwargs):
        interval = CAPTION_PROXY_INTERVAL_S if self.proxied else CAPTION_MIN_INTERVAL_S
        with self._lock:
            wait = _ThrottledSession._next_at[self.proxied] - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _ThrottledSession._next_at[self.proxied] = time.monotonic() + interval
        kwargs.setdefault("timeout", CAPTION_TIMEOUT_S)
        return super().request(*args, **kwargs)


def proxy_url() -> str:
    """CAPTION_PROXY_URL on a new proxy session, so a new IP."""
    return CAPTION_PROXY_URL.replace("{session}", uuid.uuid4().hex[:12])


def caption_session(proxied: bool | None = None, proxy: str | None = None) -> requests.Session:
    """A fresh session (no cookies) for one video; when proxied (by default,
    whenever CAPTION_PROXY_URL is set) on `proxy`, or a new proxy session."""
    proxied = _route(proxied)
    session = _ThrottledSession(proxied)
    if proxied:
        url = proxy or proxy_url()
        session.proxies = {"http": url, "https": url}
    return session


def _route(proxied: bool | None) -> bool:
    """Whether to use the proxy: never without CAPTION_PROXY_URL."""
    return bool(CAPTION_PROXY_URL) and (proxied is None or proxied)


_captions_blocked_until = {False: 0.0, True: 0.0}
_proxy_strikes = 0


def _pause_captions(reason: str, proxied: bool) -> None:
    _captions_blocked_until[proxied] = time.monotonic() + CAPTION_COOLDOWN_S
    route = "through the proxy" if proxied else "from our own IP"
    print(f"{reason}; no captions {route} for the next {CAPTION_COOLDOWN_S / 60:.0f} min, "
          f"those videos go to Whisper")


def caption_text(info: dict, language: str, proxied: bool | None = None,
                 proxy: str | None = None) -> str | None:
    """The video's caption text, or None when there is no usable track, the
    track reads as another language, or YouTube is blocking caption requests
    on this route. proxied=None means the proxy whenever one is configured.
    `proxy` is the session the metadata read used, so both requests share an
    IP; a retry after a block takes a new one."""
    global _proxy_strikes
    proxied = _route(proxied)
    if time.monotonic() < _captions_blocked_until[proxied]:
        return None
    video_id = info.get("id")
    attempts = 2 if proxied else 1
    for attempt in range(attempts):
        try:
            start_time = time.time()
            text = fetch_transcript(info, language,
                                    caption_session(proxied, proxy if attempt == 0 else None))
            print(f"Transcript fetched in {time.time() - start_time:.2f} seconds")
            _proxy_strikes = 0
            break
        except requests.exceptions.ProxyError as e:
            reason = str(e).rsplit("failed: ", 1)[-1].split("'")[0][:80]
            _pause_captions(f"The caption proxy refused the request ({reason})", proxied)
            return None
        except CaptionsBlocked:
            if attempt + 1 < attempts:
                print(f"Caption request for {video_id} blocked; retrying on a new IP")
                continue
            if proxied:
                _proxy_strikes += 1
            if not proxied or _proxy_strikes >= CAPTION_PROXY_STRIKES:
                _pause_captions("YouTube is blocking caption requests (HTTP 429)", proxied)
            return None
        except Exception as e:
            print(f"No usable '{language}' captions for {video_id} "
                  f"({type(e).__name__}: {(str(e).splitlines() or [''])[0][:120]})")
            return None

    if not transcript_language_matches(text, language):
        print(f"Caption track for {video_id} is labelled '{language}' but reads as "
              f"another language; not using it")
        return None
    return text


def caption_track(info: dict, language: str) -> str | None:
    """URL of the json3 track for `language` in yt-dlp's info, or None.

    Matched on the primary subtag: YouTube labels tracks 'es', 'pt-BR' or
    'en-US' while `language` is a bare ISO 639-1 code. Manual tracks
    ("subtitles") beat automatic ones; among automatic tracks only YouTube's
    own speech recognition counts. "automatic_captions" also lists a machine
    translation into ~150 languages, each with a tlang parameter in its URL,
    and an English video's translated 'es' track would read as Spanish and
    pass the language check -- so a URL with tlang is never used.
    """
    target = language.lower()

    def json3(formats):
        return next((f["url"] for f in formats or []
                     if f.get("ext") == "json3" and "m3u8" not in (f.get("protocol") or "")), None)

    def ranked(tracks: dict) -> list:
        codes = [c for c in tracks if c.split("-")[0].lower() == target]
        # Exact code (or YouTube's '<code>-orig' ASR original) first, then
        # regional variants in the order YouTube listed them.
        return sorted(codes, key=lambda c: (c.lower() not in (target, f"{target}-orig"),
                                            not c.endswith("-orig"), list(tracks).index(c)))

    manual = info.get("subtitles") or {}
    for code in ranked(manual):
        if url := json3(manual[code]):
            return url
    automatic = info.get("automatic_captions") or {}
    for code in ranked(automatic):
        url = json3(automatic[code])
        if url and "tlang" not in urllib.parse.parse_qs(urllib.parse.urlparse(url).query):
            return url
    return None


def json3_text(data: dict) -> str:
    """The cue text of a json3 track, without [Música]-style sound tags."""
    cues = []
    for event in data.get("events") or []:
        text = "".join(seg.get("utf8", "") for seg in event.get("segs") or []).strip()
        if text and not (text.startswith("[") and text.endswith("]")):
            cues.append(text)
    return re.sub(r"\s+", " ", " ".join(cues)).strip()


def fetch_transcript(info: dict, language: str, session: requests.Session | None = None) -> str:
    """The caption text for `language`, in one request to the track URL.

    Raises NoCaptions when the video has no usable track, which main() treats
    as a reason to transcribe the audio, and CaptionsBlocked on HTTP 429.
    """
    url = caption_track(info, language)
    if not url:
        raise NoCaptions(f"no '{language}' track")
    response = (session or caption_session()).get(url)
    if response.status_code == 429:
        raise CaptionsBlocked(info.get("id"))
    response.raise_for_status()
    text = json3_text(response.json())
    if not text:
        raise NoCaptions("empty track")
    return text


def main(url, language: str, use_captions=True, use_proxy=True):
    
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
    
    try:
        # Whisper-only runs read on our own IP: they download from it anyway.
        # use_proxy=False keeps a caption video on our own IP too.
        # One proxy session per video: its metadata read and caption track
        # come from the same IP.
        proxied = use_captions and _route(use_proxy)
        info, session = read_info(url, proxied)
        title = info.get("title")
        creator = info.get("channel") or info.get("uploader")
        tags = info.get("tags") or []
        views = info.get("view_count")
        length = info.get("duration")  # Duration in seconds
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
    if use_captions:
        text = caption_text(info, language, proxied, session)
        if text:
            with open(txt_filename, "w", encoding='utf-8') as txt_file:
                txt_file.write(text)
            process_transcription(txt_filename, video_id, title, creator, tags, views, length, date_added, language)
            return

    audio_file = download_video(info)
    if not audio_file and proxied:
        # The format URL is signed for the proxy's IP. It downloaded from ours
        # when tested, but if Google enforces that, read the page again here.
        print(f"Retrying the download for {video_id} after a read on our own IP")
        audio_file = download_video(video_info(url))
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
        
        groups = group_text(filtered_text)
        content = parse(groups, video_id, language)


        # Prepare the complete metadata dictionary
        result = {
            "title": title,
            "id": video_id,
            "tags": list(set(tags)),
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