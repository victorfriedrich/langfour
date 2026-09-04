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

    if use_transcript_api:
        try:
            start_time = time.time()
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
            # TODO: Localize based on language
            # Música
            merged_text = ' '.join(
                item['text'] for item in transcript if item['text'] != '[Musik]'
            )
            with open(txt_filename, "w", encoding='utf-8') as txt_file:
                txt_file.write(merged_text)
            end_time = time.time()
            print(f"Transcript fetched and saved in {end_time - start_time:.2f} seconds")
            process_transcription(txt_filename, video_id, title, creator, tags, views, length, date_added, language)
        except TranscriptsDisabled:
            raise Exception(f"Subtitles are disabled for video {video_id}.")
        except NoTranscriptFound:
            raise Exception(f"No transcripts found for language '{language}' for video {video_id}.")
        except Exception as e:
            raise Exception(f"Error fetching transcript via YouTubeTranscriptApi for video {video_id}: {str(e)}")
    else:
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