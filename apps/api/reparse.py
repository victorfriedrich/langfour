
import os
import json
from typing import Dict, List, Any
from database import word_cache, initialize_cache, identify_word_id
from nlp_processing import add_to_dictionary
from paths import processed_file
from paths import processed_dir
from languages import to_code

# TODO: Identify source and language of video
def reparse_missing_words(content: List[Dict[str, Any]], word_cache: Dict[str, Dict[str, int]], language: str, source: str) -> List[Dict[str, Any]]:
    reparsed_content = []
    
    for item in content:
        if 'id' in item:
            word_id = item['id']
            word = item['content'].lower()
            
            # Check if the ID exists in the cache
            id_exists = any(word_id in cache.values() for cache in word_cache[language].values())
            
            if not id_exists and word != "quot":
                # Word ID is missing from the cache, so we need to reparse
                
                # TODO: Refine error handling
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

def process_all_videos_in_folder(language: str):
    initialize_cache()
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

# Example usage
process_all_videos_in_folder('german')