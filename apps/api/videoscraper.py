import json
import os
import tempfile
import logging
from database import initialize_cache
from videoparsing import main as process_video
from paths import processed_file, data_file

# Configuration
CHANNEL_LIST  = str(data_file("yt_es.json"))
LANGUAGE      = "spanish"
LANGUAGE_CODE = "es"

# Set up error logging
logging.basicConfig(
    filename='video_processing_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def save_progress(data, path=CHANNEL_LIST):
    """Atomically rewrite *path* with *data*."""
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".tmp_", suffix=".json", text=True)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())        # make sure bytes hit disk
        os.replace(tmp, path)            # atomic swap
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)               # clean up on failure

def _process_and_mark(channel_name, video):
    """Helper: process a single video and mark its status."""
    vid = video.get('id')
    url = f"https://www.youtube.com/watch?v={vid}"
    print(f"Processing video: {vid} from channel: {channel_name}")
    try:
        process_video(url, LANGUAGE)
        processed_filename = str(processed_file(LANGUAGE_CODE, vid))
        if os.path.exists(processed_filename):
            video['processed'] = "processed"
            print(f"Successfully processed video: {vid}")
        else:
            raise FileNotFoundError(f"Processed file not found: {processed_filename}")
    except Exception as e:
        video['processed'] = "failedrec"
        msg = f"Error processing video {vid}: {e}"
        print(msg)
        logging.error(msg)

def process_videos(process_even=True):
    """Process prioritized first; if none, process unprocessed by parity filter."""
    initialize_cache()

    # Load channel list
    with open(CHANNEL_LIST, 'r') as f:
        data = json.load(f)

    # === PASS 1: prioritized videos ===
    prioritized_count = 0
    for channel in data:
        name = channel.get('Name')
        for video in channel.get('Videos', []):
            if video.get('processed') == "prioritized":
                _process_and_mark(name, video)
                prioritized_count += 1
                save_progress(data)

    if prioritized_count > 0:
        print(f"Finished processing {prioritized_count} prioritized video(s).")
        print("All done.")
        return

    # === PASS 2: unprocessed videos (skip processed/failed) ===
    unprocessed_count = 0
    for channel in data:
        name   = channel.get('Name')
        videos = channel.get('Videos', [])
        for idx, video in enumerate(videos):
            status = video.get('processed', 'unprocessed')
            # only even or odd slots, and only truly unprocessed ones
            if status == "unprocessed" or status == "failed" and \
               ((process_even and idx % 2 == 0) or (not process_even and idx % 2 != 0)):
                _process_and_mark(name, video)
                unprocessed_count += 1
                save_progress(data)

    if unprocessed_count:
        print(f"Finished processing {unprocessed_count} unprocessed video(s).")
    else:
        print("No unprocessed videos matched the filter; skipping that step.")
    print("All done.")

if __name__ == "__main__":
    # Set process_even=False to process odd-indexed videos,
    # or process_even=True for even-indexed.
    process_videos(process_even=True)
