#!/usr/bin/env python3
"""Fill in words.cognate — how close a word is to its English counterpart.

    python3 scripts/cognates.py

Pages the words table, asks the model to classify each root, and writes the
answer back in batches. Distinct from language_flagging.py, which writes the
sentinel value "invalid" into the same column to mark a word for review.
"""
import json
import os
import sys
from typing import Dict, List

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()

from llm_client import client  # noqa: E402
from models import MODEL_SMART  # noqa: E402
from supabase_client import supabase  # noqa: E402


def fetch_words(batch_size: int = 50, offset: int = 0) -> List[Dict]:
    """Fetch words from the database with given batch size and offset."""
    response = supabase.table("words").select("id, root").range(offset, offset + batch_size - 1).execute()
    return response.data

def parse_chatgpt_output(output: str, startChar: str, endChar: str) -> str:
    """Extract JSON output from ChatGPT's response."""
    start = output.find(startChar)
    end = output.rfind(endChar)
    
    if start == -1 or end == -1 or start > end:
        raise ValueError("No valid JSON object found in the output")
    
    json_content = output[start:end+1]
    return json_content

def analyze_cognates(words: List[Dict]) -> List[Dict]:
    """Analyze the words to determine their cognates using ChatGPT."""
    word_list = [word['root'] for word in words]
    prompt = f"""Analyze the following Spanish words and determine if they are similar to an English or French word with the same meaning. 
    Consider a word to have a cognate if it's similar enough that knowledge of English or French would help in understanding or remembering the Spanish word.
    
    Return a JSON object where the key is the Spanish word and the value is:
    - 'english' if it has an English cognate
    - 'french' if it has a French cognate
    - 'other' if it's not really a Spanish word, but a company or name of a person or not a spanish word
    - null if it doesn't have a cognate in English or French
    
    Be conservative in your assessment whether a french and english speaker would know the cognate.
    :\n\n{', '.join(word_list)}"""

    response = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
        temperature=0.3,
    )

    raw_output = response.choices[0].message.content
    json_output = parse_chatgpt_output(raw_output, '{', '}')
    cognates = json.loads(json_output)

    return [{"id": word['id'], "root": word['root'], "cognate": cognates.get(word['root'], None)} for word in words]

def update_cognates(cognate_data: List[Dict]):
    """Update the cognate information in the database for existing words."""
    word_ids = [data['id'] for data in cognate_data]
    
    # Fetch existing words from the database to ensure proper matching
    response = supabase.table("words").select("id, root").in_("id", word_ids).execute()
    current_words = {word['id']: word['root'] for word in response.data}

    updates = []
    for data in cognate_data:
        # Only update if the word exists and the root matches
        if data['id'] in current_words and current_words[data['id']] == data['root']:
            updates.append(data)
        else:
            print(f"Skipped update for word: {data['root']} (ID mismatch or not found)")

    # Perform individual updates to ensure the WHERE clause is correct
    for update in updates:
        supabase.table("words").update({"cognate": update["cognate"]}).eq("id", update["id"]).execute()

    print(f"Updated cognate status for {len(updates)} words.")


def main(offset: int = 0):
    batch_size = 50

    while True:
        print(f"Fetching words (offset: {offset})...")
        words = fetch_words(batch_size, offset)
        
        if not words:
            print("No more words to process.")
            break

        print(f"Analyzing cognates for {len(words)} words...")
        cognate_data = analyze_cognates(words)

        print("Updating database with cognate information...")
        update_cognates(cognate_data)

        print(f"Processed {len(cognate_data)} words.")
        offset += batch_size

if __name__ == "__main__":
    # Optional argument resumes a long run from the offset the loop last printed.
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
