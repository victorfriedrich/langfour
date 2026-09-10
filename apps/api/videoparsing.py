from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import json
import time
from dotenv import load_dotenv
import pytubefix as pytube
from moviepy.editor import VideoFileClip
import os
from llm_client import transcription_client
from models import MODEL_TRANSCRIBE
import traceback
from nlp_processing import filter_entities, parse, group_text, get_tags
from languages import require_code
from datetime import datetime
from paths import processed_file

load_dotenv()

# Whisper runs on DeepInfra: OpenRouter has no /audio/transcriptions
# endpoint. The client is built lazily inside the function, so importing
# this module does not require a DeepInfra key.

def download_video(url):
    try:
        video = pytube.YouTube(url, 'ANDROID')
        stream = video.streams.filter(only_audio=True).first()
        audio_file = stream.download()
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

def transcribe_audio(mp3_filename, video_id):
    # Ensure the 'transcripts' directory exists
    os.makedirs("transcripts", exist_ok=True)
    
    txt_filename = os.path.join("transcripts", f"{video_id}.txt")
    if os.path.exists(txt_filename):
        print(f"Transcription file {txt_filename} already exists. Skipping transcription.")
        return txt_filename
    
    try:
        start_time = time.time()
        with open(mp3_filename, "rb") as audio_file:
            transcription = transcription_client().audio.transcriptions.create(
                model=MODEL_TRANSCRIBE,
                file=audio_file,
                response_format="text"
            )
        # response_format="text" yields a bare string on OpenAI; DeepInfra may
        # return a transcription object instead. Accept either.
        text = transcription if isinstance(transcription, str) else transcription.text
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
        from ytpipeline import clean, DETECT_LANGS, MIN_CONF
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


def fetch_transcript(video_id: str, language: str):
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
    available = YouTubeTranscriptApi().list(video_id)
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

    # Captions when they exist, Whisper when they do not. This used to raise on
    # a missing or disabled track, which ended the video: ingest.transcribe()
    # caught the exception and wrote status='failed', permanently. The audio
    # path below was unreachable from the queue, because ingest calls main()
    # with two arguments and the default left use_transcript_api True -- so
    # moviepy, pytubefix and the Whisper client were all shipped for a branch
    # nothing could enter, while the library rot below silently failed
    # every single video.
    transcript = None
    if use_transcript_api:
        try:
            start_time = time.time()
            transcript = fetch_transcript(video_id, language)
            print(f"Transcript fetched in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            # Deliberately any failure, not just the library's two typed ones.
            # youtube_transcript_api is a scraper, and a scraper's failure mode
            # is not always a tidy exception: 0.6.2 listed caption tracks fine
            # but returned an empty body when it fetched one, surfacing as an
            # xml.etree ParseError that no `except` here named. Narrowing this
            # back to (TranscriptsDisabled, NoTranscriptFound) would let the
            # next round of rot -- and there will be one -- end videos that
            # Whisper could have transcribed.
            print(f"No usable '{language}' captions for {video_id} "
                  f"({type(e).__name__}: {str(e).splitlines()[0][:120]}); "
                  f"falling back to audio transcription")

    if transcript is not None:
        # TODO: Localize based on language
        # Música
        # 1.x yields FetchedTranscriptSnippet objects, not dicts.
        merged_text = ' '.join(
            snippet.text for snippet in transcript if snippet.text != '[Musik]'
        )
        if transcript_language_matches(merged_text, language):
            with open(txt_filename, "w", encoding='utf-8') as txt_file:
                txt_file.write(merged_text)
            process_transcription(txt_filename, video_id, title, creator, tags, views, length, date_added, language)
            return
        print(f"Caption track for {video_id} is labelled '{language}' but reads as "
              f"another language; ignoring it and transcribing the audio instead")
        transcript = None

    if transcript is None:
        mp4_filename = download_video(url)
        if mp4_filename:
            mp3_filename = mp4_filename
            if mp3_filename:
                transcription_file = transcribe_audio(mp3_filename, video_id)
                if transcription_file:
                    print(f"Transcription saved as: {transcription_file}")
                    process_transcription(transcription_file, video_id, title, creator, tags, views, length, date_added, language)
                else:
                    print("Transcription failed.")
                cleanup_files(mp4_filename, mp3_filename)
            else:
                print("MP3 conversion failed.")
        else:
            print("Video download failed.")

def process_transcription(txt_filename, video_id, title, creator, tags, views, length, date_added, language):
    try:
        start_time = time.time()
        with open(txt_filename, 'r', encoding='utf-8') as file:
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
        raise Exception(f"Error in processing transcript: {str(e)}")