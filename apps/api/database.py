import logging

from dotenv import load_dotenv

from llm_client import client
from models import MODEL_FAST

load_dotenv()

# These are both the in-memory cache keys and the values sent to Postgres as
# words.language, so they follow the column: ISO codes. Sourced from
# languages.py rather than restated, which is how this list came to be missing
# Italian while the words table held 36k Italian rows.
from languages import SUPPORTED_CODES, display_name, to_code
from supabase_client import supabase

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

                # Add wordform to the wordform cache only if it exists. The
                # first root wins: roots arrive in ascending id order, and a
                # form shared by two roots is usually a real word plus a junk
                # copy created later (an English or misspelt root carrying the
                # same Spanish forms). Overwriting let the newer, junk root
                # capture the form -- 'editaron' linked to 'edit'.
                if wordform:
                    word_cache[language]['wordforms'].setdefault(wordform, word_id)

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


def save_to_supabase(root: str, forms: set, language: str, source: str | None = None,
                      translation: str | None = None, status: str = 'unverified'):
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
    :param status: Dictionary verdict shared by the new root and its forms.
        Only invalid entries are excluded from matching.
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
            "status": status,
        }).execute()
        word_id = response.data[0]['id']

        # Update the cache with the new word
        if status != 'invalid':
            word_cache[language]['words'][root.lower()] = word_id

        # Prepare the additional forms for insertion
        form_entries = [{"word_id": word_id, "form": form, "status": status} for form in forms]
        formstring = ""
        if len(forms) <= 4:
            formstring = str(forms)
        else:
            formstring = f"{list(forms)[:3]}..., {len(forms)} in total"
        print(f"Added {root} ({word_id}) | {formstring} | status={status}")

        if form_entries:
            supabase.table("wordforms").upsert(form_entries).execute()

            # Match the status rule used when loading the cache from SQL.
            if status != 'invalid':
                for form in forms:
                    # A new root never takes over a form another root owns.
                    word_cache[language]['wordforms'].setdefault(form.lower(), word_id)

        return word_id if status != 'invalid' else None

    except Exception as e:
        if 'duplicate key value violates unique constraint' in str(e):
            print(f"Root word '{root}' already exists in {language}. Adding new forms.")
            try:
                # Get the existing word_id
                response = supabase.table("words").select("id, status").eq("root", root).eq("language", language).limit(1).execute()
                existing_word_id = response.data[0]['id']
                if response.data[0]['status'] == 'invalid':
                    return None

                # A duplicate name is not a verdict; retain the root's audit.
                if translation:
                    supabase.table("words").update({"translation": translation}).eq("id", existing_word_id).execute()

                # Preserve existing form verdicts too, including invalid ones.
                for form in forms:
                    response = supabase.table("wordforms").upsert({
                        "word_id": existing_word_id,
                        "form": form,
                        "status": status,
                    }, on_conflict="word_id,form", ignore_duplicates=True).execute()
                    if response.data and status != 'invalid':
                        word_cache[language]['wordforms'].setdefault(form.lower(), existing_word_id)

                return existing_word_id if status != 'invalid' else None
            except Exception as form_error:
                print(f"Error adding wordform: {form_error}")
        else:
            print(f"Error saving to Supabase: {e}")

def find_roots(roots: list[str], language: str) -> dict[str, dict]:
    """Existing roots for `roots`, matched without case, invalid ones included,
    keyed by the lowercased root: {'el coche': {'id': .., 'status': ..}}.

    One request for any number of roots (sql/find_roots.sql). The old lookup was
    one ILIKE request per root, which no index serves: ~350 ms each.
    """
    found: dict[str, dict] = {}
    for i in range(0, len(roots), 500):
        rows = supabase.rpc("find_roots", {"language_param": language_key(language),
                                           "roots": roots[i:i + 500]}).execute().data
        for row in rows:     # lowest id first, like the cache
            found.setdefault(row["root"].lower(), {"id": row["id"], "status": row["status"]})
    return found


def find_dictionary_root(root: str, language: str) -> dict | None:
    """Find an existing root, including invalid entries, without matching forms.

    Creation uses this to preserve audit decisions; token matching must check
    the returned status before using its id.
    """
    root = root.strip()
    return find_roots([root], language).get(root.lower())


def cached_word_id(word: str, language: str) -> int | None:
    """The word's id from the in-memory cache, or None. No database call."""
    cache = word_cache[language_key(language)]
    word_lower = word.lower().strip()
    word_title = word.title().strip()
    if word_lower in cache['words']:
        return cache['words'][word_lower]
    if word_title in cache['words']:
        return cache['words'][word_title]
    return cache['wordforms'].get(word_lower)


def resolve_uncached(words: list[str], language: str) -> dict[str, int]:
    """Ids for cache misses whose root was added after the cache loaded (by
    another worker), in one request. Invalid roots don't count as matches."""
    language = language_key(language)
    found = {}
    for root, row in find_roots(words, language).items():
        if row['status'] != 'invalid':
            word_cache[language]['words'][root] = row['id']
            found[root] = row['id']
    return found


def identify_word_id(word: str, language: str):
    """
    Identify the word ID for a given word in a specific language.
    :param word: The word to identify.
    :param language: The language of the word.
    :return: The word ID.
    """
    language = language_key(language)
    word_id = cached_word_id(word, language)
    if word_id is not None:
        return word_id

    # If not found in cache, attempt to fetch from the database
    print(f"{word} not found in {language} cache")
    try:
        word_lower = word.lower().strip()
        word_id = resolve_uncached([word_lower], language).get(word_lower)
        if word_id is not None:
            return word_id
    except Exception as e:
        print(f"Error fetching word '{word}' from Supabase: {e}")

    raise ValueError(f"Word '{word}' not found in language '{language}'")

def get_words_with_many_forms():
    response = supabase.rpc("get_words_with_many_forms").execute()
    return response.data

def insert_gerundio_form(gerundio_entry: dict):
    supabase.table("wordforms").insert(gerundio_entry).execute()

def get_missing_words_from_db(user_id: str, word_ids: list[int], language: str) -> list[dict]:
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
    """Reload through the status-aware RPC, including changes to older forms."""
    initialize_cache()

def add_wordform(wordform: str, root_id: int, language: str,
                 status: str = 'unverified') -> int | None:
    """
    Add a new wordform to an existing root, and update the cache.
    :param wordform: The wordform to add.
    :param root_id: The ID of the root word.
    :param language: The language of the wordform.
    :param status: The verdict for this form, independent of the root's audit.
    :return: The root word ID.
    """
    language = language_key(language)
    try:
        # Add the new wordform and associate it with the found root ID
        supabase.table("wordforms").insert({
            "word_id": root_id,
            "form": wordform,
            "status": status,
        }).execute()

        # Flagged means awaiting review, not invalid. Do not overwrite the
        # root's independent verdict because of a new form.
        if status != 'invalid':
            word_cache[language]['wordforms'].setdefault(wordform.lower(), root_id)
        
        return root_id if status != 'invalid' else None
    except Exception as e:
        print(f"Error adding wordform '{wordform}' in language '{language}': {e}")
        raise

def invalid_root_ids(ids: list[int]) -> set[int]:
    """Of `ids`, the roots an audit marked invalid. The deployed cache function
    still loads invalid roots (without their forms), so callers check here."""
    found: set[int] = set()
    for i in range(0, len(ids), 300):
        rows = (supabase.table("words").select("id").in_("id", ids[i:i + 300])
                .eq("status", "invalid").execute().data)
        found.update(r["id"] for r in rows)
    return found


def existing_wordforms(pairs: list[tuple[int, str]]) -> dict[tuple[int, str], str]:
    """Status of each (root id, form) row that already exists. The cache leaves
    out invalid forms, so a token can miss it and still have a row."""
    if not pairs:
        return {}
    rows = (supabase.table("wordforms").select("word_id, form, status")
            .in_("word_id", sorted({w for w, _ in pairs}))
            .in_("form", sorted({f for _, f in pairs})).execute().data)
    wanted = set(pairs)
    return {(r["word_id"], r["form"]): r["status"] for r in rows
            if (r["word_id"], r["form"]) in wanted}


def record_pending_words(rows: list[dict]) -> None:
    """Keep tokens parse() did not attach for a later pass (sql/pending_words.sql)."""
    if rows:
        supabase.rpc("record_pending_words", {"rows": rows}).execute()


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
            "Don't include the article in the translation for nouns. "
            # Nouns are stored with their article (el amanecer), so a bare
            # infinitive is the verb and must not get the noun's meaning.
            "Nouns are written with their article; a word without one is not a noun, "
            "so translate it in its own word class (a verb gets the verb's meanings, without 'to'): "
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
