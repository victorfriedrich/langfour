import os
import json
import time
import traceback
from dotenv import load_dotenv
from nlp_processing import parse, group_text, summarize_text

load_dotenv()

from paths import ARTICLES_DIR as _ARTICLES_PATH
ARTICLES_DIR = str(_ARTICLES_PATH)

def process_text(text, article_id, language: str):
    """
    Process text by tokenizing it with the new group_text function,
    and then parsing those groups to assign IDs to words.
    """
    try:
        start_time = time.time()
        # Use the new grouping mechanism to tokenize text.
        tokens = group_text(text)
        print("Tokens after grouping:", tokens)
        
        # Parse tokens to obtain a list of dicts with "content" and optional "id"
        parsed_result = parse(tokens, article_id, language)
        
        end_time = time.time()
        print(f"Text processing completed in {end_time - start_time:.2f} seconds")
        return parsed_result
    except Exception as e:
        print(f"Error processing text: {e}")
        traceback.print_exc()
        return None

def save_article(title, content):
    try:
        os.makedirs(ARTICLES_DIR, exist_ok=True)
        file_path = os.path.join(ARTICLES_DIR, f"{title}.json")
        with open(file_path, "w") as f:
            json.dump(content, f, indent=2)
        return file_path
    except Exception as e:
        print(f"Error saving article: {e}")
        return None

def parse_article(text, language: str):
    try:
        # Summarize the text to generate a title.
        title = summarize_text(text)
        print("summary", title)
        
        # Process the text using the refactored process_text.
        parsed_content = process_text(text, "user_input", language)
        
        if parsed_content:
            full_content = {
                "title": title,
                "content": parsed_content
            }
            file_path = save_article(title, full_content)
            if file_path:
                print(f"Article saved to {file_path}")
                return title, parsed_content
            else:
                print("Failed to save article.")
        else:
            print("Failed to process text.")
    except Exception as e:
        print(f"Error in main function: {e}")
        return None