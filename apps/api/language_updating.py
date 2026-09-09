import json

from dotenv import load_dotenv

load_dotenv()

from languages import require_code
from llm_client import client
from models import MODEL_SMART

# Initialize Supabase client
from supabase_client import supabase
from utils import parse_chatgpt_output


def fetch_words_without_translation(batch_size: int = 40, offset: int = 0, language: str = "es") -> list[dict]:
    # Was a hardcoded "spanish" against words.language, which now holds ISO
    # codes -- it would have quietly returned zero rows forever.
    response = supabase.table("words").select("id, root").eq("language", require_code(language)).is_("translation", None).order("id", desc=False).range(offset, offset + batch_size - 1).execute()
    return response.data

def get_translations(words: list[dict]) -> list[dict]:
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

def update_translations(translations: list[dict]):
    for translation in translations:
        supabase.table("words").update({"translation": translation['translation']}).eq("id", translation['id']).execute()
        print(f"Updated translation for word: {translation['root']}")

def main():
    offset = 0
    batch_size = 40

    while True:
        print(f"Fetching words without translation (offset: {offset})...")
        words = fetch_words_without_translation(batch_size, offset)
        
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
    main()
