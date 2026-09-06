#!/usr/bin/env python3
"""Repair transcripts that point at word ids no longer in the database.

    python3 scripts/reparse.py <language> [video_id]

Stage 4 of four, and the reason the other three are safe to run. When you delete
words through the web app's WordValidation view — the rows language_flagging.py
marked cognate = "invalid" — every transcript on disk still carries the deleted
ids. This walks those files, finds ids absent from the word cache, and re-resolves
each token against the dictionary.

A token whose word is genuinely gone gets id = None, which is correct: it was
deleted because it is not a word, so it should stop pointing at a dictionary
entry. Re-adding it would undo the deletion you just made.

With no video_id it processes every transcript for the language, which is what a
bulk delete calls for. Pass one to repair a single video.
"""
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import identify_word_id, initialize_cache, word_cache  # noqa: E402
from languages import to_code  # noqa: E402
from paths import processed_dir, processed_file  # noqa: E402


def reparse_missing_words(content: List[Dict[str, Any]], word_cache: Dict[str, Dict[str, int]], language: str, source: str) -> List[Dict[str, Any]]:
    """Re-resolve every token whose id is no longer in the cache.

    `source` is threaded through for the disabled add_to_dictionary path below and
    is otherwise unused -- callers pass the video id.
    """
    reparsed_content = []
    
    for item in content:
        if 'id' in item:
            word_id = item['id']
            word = item['content'].lower()
            
            # Check if the ID exists in the cache
            id_exists = any(word_id in cache.values() for cache in word_cache[language].values())
            
            if not id_exists and word != "quot":
                # Word ID is missing from the cache, so we need to reparse
                
                # None is the intended outcome, not a swallowed error: the word
                # was deleted because it is not a word, so the token should stop
                # pointing at a dictionary entry. The commented line below is the
                # rejected alternative -- it would re-add what was just deleted.
                try:
                    new_id = identify_word_id(word, language)
                except ValueError:
                    new_id = None
                    # new_id = add_to_dictionary(word, source, language)
                    
                item['id'] = new_id
        reparsed_content.append(item)
    
    return reparsed_content

def process_youtube_script(script_json: str, word_cache: Dict[str, Dict[str, int]], language: str, source: str) -> str:
    data = json.loads(script_json)
    data['content'] = reparse_missing_words(data['content'], word_cache, language, source)
    return json.dumps(data, ensure_ascii=False, indent=2)

def process_video_id(id: str, language: str):
    """Repair one transcript. Requires an initialised cache -- see _ensure_cache."""
    print(f'Initializing processing for {id}')
    # Was a local map covering only Italian and German, so Spanish and French
    # silently returned None and skipped every video. Normalised into
    # `language` itself: it is also the word_cache key downstream, and
    # converting only the path variable left the cache lookup on the long name.
    language = to_code(language)

    if not language:
        print(f"Unsupported language: {language}")
        return

    file_path = str(processed_file(language, id))
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        script_json = f.read()
        updated_json = process_youtube_script(script_json, word_cache, language, id)
    
    # Write the updated JSON back to the file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(updated_json)
    
    print(f"Processed video ID: {id}")

def _ensure_cache():
    """Fill word_cache if it is still the empty skeleton database.py defines.

    Only process_all_videos_in_folder used to call initialize_cache(), so calling
    process_video_id directly -- the obvious thing to do after deleting a single
    word -- left every lookup missing the cache and falling through to one
    database query per token.
    """
    if not any(c["words"] or c["wordforms"] for c in word_cache.values()):
        initialize_cache()


def process_all_videos_in_folder(language: str):
    _ensure_cache()
    language = to_code(language)

    if not language:
        print(f"Unsupported language: {language}")
        return

    folder_path = str(processed_dir(language)) + '/'
    
    if not os.path.exists(folder_path):
        print(f"Folder not found: {folder_path}")
        return
    
    for filename in os.listdir(folder_path):
        if filename.endswith('_processed.json'):
            video_id = filename.split('_')[0]
            process_video_id(video_id, language)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/reparse.py <language> [video_id]")
        sys.exit(1)

    lang = sys.argv[1]
    if len(sys.argv) > 2:
        _ensure_cache()
        process_video_id(sys.argv[2], lang)
    else:
        process_all_videos_in_folder(lang)