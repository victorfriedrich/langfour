import os
import json
import uuid
from fastapi import HTTPException
from typing import List, Dict

from paths import ARTICLES_DIR, PROCESSED_DIR
VIDEOS_DIR = str(PROCESSED_DIR)
SPECIAL_CHARACTERS = '.,!?¿¡\'"""''1234567890()«»%: -_[]{}#@$&*+=|\\<>/~`^“”…;\n\r\t'

def generate_title(text: str) -> str:
    return str(uuid.uuid4())[:8]

def is_special_character(group: str) -> bool:
    return all(char in SPECIAL_CHARACTERS for char in group)

def parse_chatgpt_output(output: str, startChar: str, endChar: str) -> str:
    start = output.find(startChar)
    end = output.rfind(endChar)
    
    if start == -1 or end == -1 or start > end:
        raise ValueError("No valid JSON array found in the output")
    
    json_content = output[start:end+1]
    return json_content

def get_video_words(video_id: str, language_code: str) -> List[Dict]:
    try:
        # First, try to find the file in the main VIDEOS_DIR
        file_path = os.path.join(VIDEOS_DIR, f"{language_code}/{video_id}_processed.json")
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:      
                return json.load(f).get("content")

        
        # If not found, search recursively in all subdirectories
        for root, dirs, files in os.walk(f"{VIDEOS_DIR}/{language_code}"):
            file_path = os.path.join(root, f"{video_id}_processed.json")
            print(file_path)
            if os.path.exists(file_path):
                print(f"3 {os.path.exists(file_path)}")
                with open(file_path, 'r') as f:
                    if language_code == "es" :
                        return json.load(f)
                    return json.load(f).get("content")

        # If still not found, raise FileNotFoundError
        raise FileNotFoundError(f"Video data not found: {video_id}")

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Video data not found: {video_id}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse JSON file")
    except Exception as e:
        print(type(e))
        raise HTTPException(status_code=500, detail=str(e))

