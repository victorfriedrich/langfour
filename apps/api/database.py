import os
from supabase import create_client, Client
from dotenv import load_dotenv
from fastapi import HTTPException
from typing import List, Dict
from llm_client import client
from models import MODEL_FAST
import logging

load_dotenv()

from supabase_client import supabase


# These are both the in-memory cache keys and the values sent to Postgres as
# words.language, so they follow the column: ISO codes. Sourced from
# languages.py rather than restated, which is how this list came to be missing
# Italian while the words table held 36k Italian rows.
from languages import SUPPORTED_CODES, display_name, to_code

SUPPORTED_LANGUAGES = list(SUPPORTED_CODES)

# Initialize the global cache with languages
word_cache = {lang: {'words': {}, 'wordforms': {}} for lang in SUPPORTED_LANGUAGES}


def language_key(language: str) -> str:
    """Normalise a caller-supplied language to the ISO code this module uses.

    Every public entry point that takes a language goes through here, for two
    reasons.

    Loud failure: a bare `word_cache[language]` on a stale value raises
    `KeyError: 'spanish'`, which reads like a missing cache entry rather than a
    caller using the pre-migration vocabulary. That is how a batch of missed
    conversion sites stayed invisible until they 500'd in production.

    Correct writes: `words.language` now carries a CHECK constraint accepting
    only ISO codes, so anything reaching an INSERT has to be normalised, not
    merely recognised.

    Long names are still accepted rather than rejected -- callers outside this
    repo (and old jobs) hold them, and mapping one is strictly better than
    failing on it.
    """
    code = to_code(language)
    if code is None:
        raise ValueError(
            f"Unsupported language {language!r}; expected one of {', '.join(SUPPORTED_LANGUAGES)}"
        )
    return code


def fetch_paginated_records(language: str, last_fetched_word_id=None, limit=1000):
    """
    Fetch records using cursor-based pagination from the custom SQL function.
    :param language: The language filter for words.
    :param last_fetched_word_id: The ID of the last fetched word for cursor pagination.
    :param limit: The number of words to fetch per page.
    :return: Fetched records (list of dictionaries).
    """
    language = language_key(language)
    result = supabase.rpc("get_words_with_wordforms_cursor", {
        "language_param": language,
        "last_fetched_word_id": last_fetched_word_id,
        "fetch_limit": limit
    }).execute()
    
    return result.data

def initialize_cache():
    """
    Initialize the cache for all supported languages.
    """
    global word_cache
    for language in SUPPORTED_LANGUAGES:
        word_cache[language] = {
            'words': {},
            'wordforms': {}
        }

        last_fetched_word_id = None
        fetch_limit = 1000  # Adjust as needed for the batch size
        has_more = True

        while has_more:
            records = fetch_paginated_records(language, last_fetched_word_id, fetch_limit)

            # Check if records were fetched
            if not records:
                print(f"Completed fetching for language: {language}, last_word_id: {last_fetched_word_id}")
                has_more = False
                break

            for record in records:
                word_id = record['word_id']
                root_word = record['word'].lower()
                
                # Handle possible NULL wordform
                wordform = record['wordform'].lower() if record['wordform'] else None

                # Add root word to the word cache
                if root_word not in word_cache[language]['words']:
                    word_cache[language]['words'][root_word] = word_id

                # Add wordform to the wordform cache only if it exists
                if wordform:
                    word_cache[language]['wordforms'][wordform] = word_id

            # Update the last fetched word ID for pagination
            last_fetched_word_id = records[-1]['word_id']
            print(last_fetched_word_id)

    # ------------------------------------------------------------------
    # Fail loudly on an empty cache.
    #
    # If the Supabase key is not service_role, or an RLS policy blocks the
    # corpus, PostgREST returns [] with HTTP 200 -- no exception. The service
    # would boot cleanly and then treat every word as unknown, producing
    # silently wrong output for every request. An empty corpus is never
    # legitimate, so refuse to start instead.
    # ------------------------------------------------------------------
    totals = {lang: len(word_cache[lang]['words']) for lang in SUPPORTED_LANGUAGES}
    if not any(totals.values()):
        raise RuntimeError(
            f"Word cache loaded 0 words for every language ({totals}). "
            "This almost always means the Supabase key is not service_role, "
            "or RLS is blocking the corpus tables. Refusing to serve."
        )
    empty = [lang for lang, n in totals.items() if n == 0]
    if empty:
        logging.warning("Word cache empty for: %s (loaded: %s)", empty, totals)
    else:
        logging.info("Word cache loaded: %s", totals)


def save_to_supabase(root: str, forms: set, language: str, source: str = None,
                      translation: str = None, flagged: bool = False):
    """
    Save a root word and its forms to Supabase and update the cache accordingly.
    :param root: The root word.
    :param forms: A set of word forms.
    :param language: The language of the word. No longer defaults to "italian":
        that default silently wrote a long name into words.language, which the
        words_language_is_iso CHECK now rejects, and keyed the cache with a
        value that no longer exists in it.
    :param source: The source of the word.
    :param translation: Translation for the root, generated alongside it by
        resolve_new_word() rather than fetched lazily on first user lookup.
    :param flagged: Whether the resolver judged this entry (root + forms) as
        not confidently a real, correctly-formed word -- same meaning and
        same column as the flag set below on a duplicate-key collision, just
        driven by content verification instead of a name collision.
    :return: The word ID.
    """
    language = language_key(language)
    word_id = None
    try:
        # Insert the root form into the Words table with the provided source and language
        response = supabase.table("words").insert({
            "root": root,
            "source": source,
            "language": language,
            "translation": translation,
            "flagged": flagged,
        }).execute()
        word_id = response.data[0]['id']

        # Update the cache with the new word
        word_cache[language]['words'][root.lower()] = word_id

        # Prepare the additional forms for insertion
        form_entries = [{"word_id": word_id, "form": form, "flagged": flagged} for form in forms]
        formstring = ""
        if len(forms) <= 4:
            formstring = str(forms)
        else:
            formstring = f"{list(forms)[:3]}..., {len(forms)} in total"
        print(f"Added {root} ({word_id}) | {formstring} | flagged={flagged}")

        if form_entries:
            supabase.table("wordforms").upsert(form_entries).execute()

            # Update the in-memory cache too, but only when not flagged --
            # otherwise this process would immediately start resolving
            # future tokens to a form we just decided was wrong, the exact
            # bug the get_words_with_wordforms_cursor filter now prevents on
            # cache (re)load.
            if not flagged:
                for form in forms:
                    word_cache[language]['wordforms'][form.lower()] = word_id

        return word_id

    except Exception as e:
        if 'duplicate key value violates unique constraint' in str(e):
            print(f"Root word '{root}' already exists in {language}. Adding new wordform and flagging.")
            try:
                # Get the existing word_id
                response = supabase.table("words").select("id").eq("root", root).eq("language", language).limit(1).execute()
                existing_word_id = response.data[0]['id']

                # Update the root word's flagged status
                update_fields = {"flagged": True}
                if translation:
                    update_fields["translation"] = translation
                supabase.table("words").update(update_fields).eq("id", existing_word_id).execute()

                # Add the new wordform and flag it
                for form in forms:
                    supabase.table("wordforms").insert({
                        "word_id": existing_word_id,
                        "form": form,
                        "flagged": True
                    }).execute()
                    # Not added to the in-memory cache: it's flagged, so it
                    # should not be matched against going forward.

                print(f"Added and flagged new wordform(s) for '{root}' (ID: {existing_word_id}) in {language}")
                return existing_word_id
            except Exception as flagging_error:
                print(f"Error adding wordform and flagging: {flagging_error}")
        else:
            print(f"Error saving to Supabase: {e}")

def identify_word_id(word: str, language: str):
    """
    Identify the word ID for a given word in a specific language.
    :param word: The word to identify.
    :param language: The language of the word.
    :return: The word ID.
    """
    global word_cache
    language = language_key(language)

    # Step 1: Cache Lookup
    word_lower = word.lower().strip()
    word_title = word.title().strip()
    
    # Check in words cache
    if word_lower in word_cache[language]['words']:
        return word_cache[language]['words'][word_lower]
    elif word_title in word_cache[language]['words']:
        return word_cache[language]['words'][word_title]

    # Check in wordforms cache
    if word_lower in word_cache[language]['wordforms']:
        return word_cache[language]['wordforms'][word_lower]
    
    # If not found in cache, attempt to fetch from the database
    print(f"{word} not found in {language} cache")
    try:
        response = supabase.table("words").select("id").eq("root", word_lower).eq("language", language).limit(1).execute()
        if response.data:
            word_id = response.data[0]['id']
            # Update the cache
            word_cache[language]['words'][word_lower] = word_id
            return word_id
    except Exception as e:
        print(f"Error fetching word '{word}' from Supabase: {e}")
    
    raise ValueError(f"Word '{word}' not found in language '{language}'")

def get_words_with_many_forms():
    response = supabase.rpc("get_words_with_many_forms").execute()
    return response.data

def insert_gerundio_form(gerundio_entry: Dict):
    supabase.table("wordforms").insert(gerundio_entry).execute()

def get_missing_words_from_db(user_id: str, word_ids: List[int], language: str) -> List[Dict]:
    """
    Get words missing from the user's word list.
    :param user_id: The user ID.
    :param word_ids: List of word IDs to check.
    :param language: The language of the words.
    :return: List of missing words.
    """
    language = language_key(language)
    
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Add logging to debug word_ids
    logger.info(f"Checking for words: {word_ids}")
    logger.info(f"User ID: {user_id}")
    
    response = supabase.table("userwords").select("word_id").eq("user_id", user_id).in_("word_id", word_ids).execute()
    existing_word_ids = {word['word_id'] for word in response.data}
    
    # Add logging for existing words
    logger.info(f"Existing words: {existing_word_ids}")

    missing_word_ids = [wid for wid in word_ids if wid not in existing_word_ids]
    
    # Add logging for missing words
    logger.info(f"Missing words: {missing_word_ids}")

    if not missing_word_ids:
        return []

    # Fetch the missing words' details
    missing_words_response = supabase.table("words").select("id, root").in_("id", missing_word_ids).eq("language", language).execute()
    
    # Add logging for response
    logger.info(f"Database response: {missing_words_response.data}")

    # Transform the data to match the expected frontend structure
    missing_words = [
        {
            "id": word['id'],
            "content": word['root'],
            "translation": None  # The frontend will fetch translations separately
        }
        for word in missing_words_response.data
    ]
    
    return missing_words

def refresh_cache():
    """
    Refresh the cache by fetching the latest words and word forms from the database.
    """
    global word_cache
    
    for language in SUPPORTED_LANGUAGES:
        # Get the latest word ID in cache for the language
        if word_cache[language]['words']:
            max_cached_word_id = max(word_cache[language]['words'].values())
        else:
            max_cached_word_id = 0

        # Fetch new words
        new_words_response = supabase.table("words").select("id, root").gt("id", max_cached_word_id).eq("language", language).execute().data
        for word in new_words_response:
            word_cache[language]['words'][word['root'].lower()] = word['id']
        
        # Fetch new word forms
        if word_cache[language]['wordforms']:
            max_cached_wordform_id = max(word_cache[language]['wordforms'].values())
        else:
            max_cached_wordform_id = 0
        new_forms_response = supabase.table("wordforms").select("word_id, form").gt("word_id", max_cached_wordform_id).or_("flagged.is.null,flagged.eq.false").execute().data
        for form in new_forms_response:
            word_cache[language]['wordforms'][form['form'].lower()] = form['word_id']

def add_and_flag_wordform(wordform: str, root_id: int, language: str, flagged: bool = True) -> int:
    """
    Add a new wordform to an existing root, and update the cache.
    :param wordform: The wordform to add.
    :param root_id: The ID of the root word.
    :param language: The language of the wordform.
    :param flagged: Whether this wordform should be marked as unverified/bad.
        Despite the function's name, this is no longer unconditionally True:
        the caller (add_to_dictionary) now passes the resolver's own verdict,
        so a genuinely valid form that simply wasn't in the dictionary yet
        isn't punished with a permanent flag just because it collided with
        an existing root.
    :return: The root word ID.
    """
    language = language_key(language)
    try:
        # Add the new wordform and associate it with the found root ID
        supabase.table("wordforms").insert({
            "word_id": root_id,
            "form": wordform,
            "flagged": flagged
        }).execute()

        # Only flag the root word if the new form is actually a problem --
        # a valid new form of an existing word is not itself evidence the
        # root is bad.
        if flagged:
            supabase.table("words").update({"flagged": True}).eq("id", root_id).execute()

        # Add the new wordform to the cache, but only if it's not flagged --
        # see the matching comment in save_to_supabase().
        if not flagged:
            word_cache[language]['wordforms'][wordform.lower()] = root_id
        
        return root_id
    except Exception as e:
        print(f"Error adding and flagging wordform '{wordform}' in language '{language}': {e}")
        raise

def get_or_create_translation(word_id: int, language: str) -> str:
    """
    Get the translation of a word. If it doesn't exist, create it using OpenAI.
    :param word_id: The ID of the word.
    :param language: The language of the word.
    :return: The translation string.
    """
    language = language_key(language)
    response = supabase.table("words").select("root, translation").eq("id", word_id).execute()
    word_data = response.data[0] if response.data else None

    if not word_data:
        print(f"Error: Word with id {word_id} not found in the database.")
        return None

    if not word_data['translation']:
        # Was an if/elif over long names that covered only Italian and Spanish,
        # so German and French silently returned None -- and after the ISO
        # migration every branch missed and *all four* returned None. The only
        # thing that varied between the branches was the English adjective, so
        # it comes from the language table instead of the control flow.
        prompt = (
            f"Translate the following {display_name(language)} word to English. "
            "Provide 1-3 comma separated words for the translation. "
            "Don't include the article in the translation for nouns: "
            f"{word_data['root']}"
        )

        try:
            response = client.chat.completions.create(
                model=MODEL_FAST,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.7,
            )
            translation = response.choices[0].message.content.strip()
            print(translation)
            # Update the translation in the database
            supabase.table("words").update({"translation": translation}).eq("id", word_id).execute()
            return translation
        except Exception as e:
            print(f"Error getting translation for word '{word_data['root']}' (ID: {word_id}): {e}")
            return None
    
    return word_data['translation']

def find_root_by_wordform_id(wordform_id: int, language: str) -> str:
    """
    Find the root word associated with a given wordform ID.
    :param wordform_id: The ID of the wordform.
    :param language: The language of the wordform.
    :return: The root word or None if not found.
    """
    language = language_key(language)
    # Iterate through the words in the cache for the specified language
    for root, word_id in word_cache[language]['words'].items():
        if word_id == wordform_id:
            return root

    # If no matching ID is found, return None
    return None