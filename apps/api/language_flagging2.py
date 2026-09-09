import json

from dotenv import load_dotenv

load_dotenv()

from llm_client import client
from models import MODEL_SMART

# Initialize Supabase client
from supabase_client import supabase
from utils import parse_chatgpt_output


def fetch_words(language: str, batch_size: int = 50, offset: int = 0) -> list[dict]:
    # Fetch words along with the first 6 wordforms of each word
    response = supabase.table("words").select("id, root").eq("language", language).range(offset, offset + batch_size - 1).execute()
    words = response.data

    # For each word, fetch its wordforms
    for word in words:
        wordform_response = supabase.table("wordforms").select("form").eq("word_id", word['id']).limit(6).execute()
        word['wordforms'] = [wf['form'] for wf in wordform_response.data]

    return words

def verify_language(words: list[dict], language: str) -> list[str]:
    formatted_terms = [
        f'root: "{word["root"]}" - {word["wordforms"]}' for word in words
    ]
    prompt = f"""Identify which of the following terms (roots) and their associated wordforms are not valid {language} words or are likely misspelled. 
    Return only the roots that correspond to problematic words or wordforms in an unnested JSON array: ["root1", "root2", ...]
    Terms to check:\n\n{', '.join(formatted_terms)}"""
    
    response = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
        temperature=0.7,
    )
    raw_output = response.choices[0].message.content
    print(raw_output)
    json_output = parse_chatgpt_output(raw_output, '[', ']')
    problematic_roots = json.loads(json_output)

    return problematic_roots

def flag_non_language_words(problematic_roots: list[str], all_words: list[dict]):
    # Update flagged status in the database
    print("flagging " + str(problematic_roots))

    word_ids_to_flag = [
        word['id'] for word in all_words if word['root'] in problematic_roots
    ]

    for word_id in word_ids_to_flag:
        supabase.table("words").update({"cognate": "invalid"}).eq("id", word_id).execute()

def main(language: str):
    offset = 9960
    batch_size = 40

    while True:
        try:
            print(f"Fetching words to verify language ({language}, offset: {offset})...")
            words = fetch_words(language, batch_size, offset)

            print(f"Verifying {len(words)} words in {language}...")
            problematic_roots = verify_language(words, language)

            if problematic_roots:
                print(f"Flagging non-{language} or misspelled words in the database...")
                flag_non_language_words(problematic_roots, words)
            else:
                print(f"No non-{language} or misspelled words found in this batch.")
        except Exception as e:
            print(f"Error filtering non-{language} words: {e!s}")
        
        offset += batch_size
        print(offset)

if __name__ == "__main__":
    language_to_check = "spanish"  # Replace with any language you'd like to verify
    main(language_to_check)