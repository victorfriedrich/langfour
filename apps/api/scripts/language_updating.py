#!/usr/bin/env python3
"""Fill in words.translation for rows that have none.

    python3 scripts/language_updating.py [language]

Stage 1 of the dictionary pipeline: everything downstream reads the translation,
including language_flagging.py, which shows it to the model as evidence.
Defaults to Spanish. Idempotent — it selects only rows where translation IS NULL,
so it can be re-run after an interruption.
"""
import json
import os
import sys
from typing import Dict, List

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()

from languages import require_code  # noqa: E402
from llm_client import client  # noqa: E402
from models import MODEL_FAST, MODEL_SMART  # noqa: E402
from supabase_client import supabase  # noqa: E402


def fetch_words_without_translation(batch_size: int = 40, offset: int = 0, language: str = "es") -> List[Dict]:
    # Was a hardcoded "spanish" against words.language, which now holds ISO
    # codes -- it would have quietly returned zero rows forever.
    response = supabase.table("words").select("id, root").eq("language", require_code(language)).is_("translation", None).order("id", desc=False).range(offset, offset + batch_size - 1).execute()
    return response.data

def parse_chatgpt_output(output: str, startChar: str, endChar: str) -> str:
    start = output.find(startChar)
    end = output.rfind(endChar)
    
    if start == -1 or end == -1 or start > end:
        raise ValueError("No valid JSON object found in the output")
    
    json_content = output[start:end+1]
    return json_content

def get_translations(words: List[Dict]) -> List[Dict]:
    word_list = [word['root'] for word in words]
    prompt = f"Please provide English equivalents for the following Spanish terms. If a word is offensive or not a valid spanish word, don't include it. For each term, offer 1-3 adequate translations, separated by commas. For nouns, omit the article in the translation. Present the results in a JSON format where the Spanish term is the key and its English equivalent is the value. Terms to translate:\n\n{', '.join(word_list)}"
    print(word_list)
    response = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2400,
        temperature=0.7,
    )
    print(response)
    raw_output = response.choices[0].message.content
    json_output = parse_chatgpt_output(raw_output, '{', '}')
    translations = json.loads(json_output)

    return [{"id": word['id'], "root": word['root'], "translation": translations.get(word['root'], '')} for word in words]

def update_translations(translations: List[Dict]):
    for translation in translations:
        supabase.table("words").update({"translation": translation['translation']}).eq("id", translation['id']).execute()
        print(f"Updated translation for word: {translation['root']}")

def main(language: str = "es", offset: int = 0):
    batch_size = 40

    while True:
        print(f"Fetching words without translation ({language}, offset: {offset})...")
        words = fetch_words_without_translation(batch_size, offset, language)
        
        if not words:
            print("No more words to process.")
            break

        print(f"Translating {len(words)} words...")
        translations = get_translations(words)

        print("Updating database with translations...")
        update_translations(translations)

        print(f"Processed {len(translations)} words.")
        offset += batch_size

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "es")
