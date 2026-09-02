from videothumbnailcreation import create_thumbnail_collage
from pydantic import BaseModel
import os
import time
import logging
from dotenv import load_dotenv
import json
from typing import List, Dict
from fastapi import HTTPException
import traceback
from database import (
    save_to_supabase,
    identify_word_id,
    get_missing_words_from_db,
    add_and_flag_wordform,
    get_or_create_translation,
    find_root_by_wordform_id
)
from itertools import groupby
from utils import is_special_character, parse_chatgpt_output, SPECIAL_CHARACTERS
from languages import require_code
from instructionmanager import INSTRUCTION_VERBS, INSTRUCTION_NOUNS, INSTRUCTION_ADJECTIVE, INSTRUCTION_SUMMARIZE, INSTRUCTION_FILTER_LANGUAGE, INSTRUCTION_ROOT_FORM, INSTRUCTION_CATEGORIZE, INSTRUCTION_HIGH_LEVEL_TAG, INSTRUCTION_VERIFY_LANGUAGE, INSTRUCTION_TRANSLATE, INSTRUCTION_VERIFY_NEW_WORD
from models import MODEL_SMART, MODEL_FAST
from llm_client import client, parse_structured
from pydantic import BaseModel
from typing import Literal, Optional, Tuple

VALID_CATEGORIES: List[str] = [
    "Beauty & Fashion", "Health & Fitness", "Products & Tech", "Gaming", "Anime",
    "Movies", "Reactions & Commentary", "Challenges & Experiments", "Comedy",
    "Travel", "Documentaries", "Cooking", "Science",
    "Politics", "Finance", "Cars", "History", "Other"
]

load_dotenv()


# TODO: Make this more efficient
def filter_entities(text: str, language: str) -> str:
    print(language)
    prompt = INSTRUCTION_FILTER_LANGUAGE[language].format(text=text)

    try:
        response = client.chat.completions.create(
            model=MODEL_FAST,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1250,
            temperature=0.4,
        )
        raw_output = response.choices[0].message.content
        json_output = parse_chatgpt_output(raw_output, '[', ']')
        
        words_to_remove = json.loads(json_output)

        # Remove the filtered words from the original text
        cleaned_text = text
        for word in words_to_remove:
            if isinstance(word, str):
                cleaned_text = cleaned_text.replace(word, '')
                cleaned_text = cleaned_text.replace(word.capitalize(), '')
        cleaned_text = ' '.join(cleaned_text.split())

        return cleaned_text
    except Exception as e:
        raise Exception(f"Error filtering non-Spanish words: {e}")
    
def get_tags(title: str, text: str):
    text = text[:2000] + "..."
    prompt = INSTRUCTION_CATEGORIZE.format(title=title, text=text)

    try:
        response = client.chat.completions.create(
            model=MODEL_FAST,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.4,
        )
        raw_output = response.choices[0].message.content
        json_output = parse_chatgpt_output(raw_output, '[', ']')
        
        return json.loads(json_output)

    except Exception as e:
        error_message = str(e)
        if "content filtering" in error_message or "Error code: 400" in error_message:
            raise Exception(f"Generating Keywords for {title} violates Azure Content Policy")
        else:
            print(f"An unexpected error occurred: {error_message}")
        return ["Failed"]

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# (Make sure you have a StreamHandler or FileHandler attached to the logger!)

def get_high_level_tag(title: str, tags: List[str]) -> str:
    system_prompt = (
        "You are a classifier.  Given a video Title and Tags, you must choose "
        "exactly one of the following high-level categories:"
    )
    user_prompt = (
        f"Title: {title}\n"
        f"Tags: {', '.join(tags)}\n\n"
        "Respond with a JSON object matching:\n"
        '{ "category": string }\n'
        "where category must be one of the allowed values."
    )
    schema = {
        "name": "high_level_tag",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": VALID_CATEGORIES
                }
            },
            "required": ["category"],
            "additionalProperties": False
        }
    }

    try:
        resp = client.chat.completions.create(
            model=MODEL_FAST,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ],
            response_format={ "type": "json_schema", "json_schema": schema },
            max_tokens=20,
            temperature=0.2,
        )

        choice = resp.choices[0]
        msg = choice.message

        # 1) Log finish reason
        logger.debug(f"finish_reason: {choice.finish_reason}")

        # 2) Log any safety refusal
        if getattr(msg, "refusal", None):
            logger.warning(f"Model refused: {msg.refusal}")
            return "Failed"

        # 3) Log raw content so you can see what JSON came back
        logger.debug(f"raw content: {repr(msg.content)}")

        # 4) Try parsing
        try:
            body = json.loads(msg.content)
            category = body.get("category")
        except json.JSONDecodeError as je:
            logger.error(f"JSON decode error: {je}")
            return "Failed"

        # 5) Validate against our enum again
        if category in VALID_CATEGORIES:
            return category
        else:
            logger.error(f"Returned category not in VALID_CATEGORIES: {category}")
            return "Failed"

    except Exception as e:
        # 6) Catch-all for networking, schema errors, etc.
        logger.exception("Exception calling Azure OpenAI:")
        return "Failed"

def get_word_root(word: str, language: str) -> str:
    prompt = INSTRUCTION_ROOT_FORM[language].format(word=word)
    
    try:
        response = client.chat.completions.create(
            model=MODEL_SMART,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=45,
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw_output = response.choices[0].message.content
        json_output = parse_chatgpt_output(raw_output, '{', '}')
        return json.loads(json_output)
    except Exception as e:
        print(f"Error finding root form: {e}")
        return None

def generate_alternatives(word: str, type: str):
    if type == "verb":
        response = client.chat.completions.create(
            model=MODEL_SMART,
            messages=[{"role": "user", "content": INSTRUCTION_VERBS.format(word=word)}],
            max_tokens=550,
            temperature=0.25,
        )
        raw_output = response.choices[0].message.content
        forms = parse_chatgpt_output(raw_output, '{', '}')
        forms = forms.lower()
        dict = json.loads(forms)
        #dict["perfecto root"] = dict["perfecto root"].split()[1:]
        
        result_set = set()
        for value in dict.values():
            if isinstance(value, list):
                result_set.update(value)
            else:
                result_set.add(value)
        return result_set
        
    elif type == "noun":
        prompt = INSTRUCTION_NOUNS.format(word=word)
    elif type == "adjective":
        prompt = INSTRUCTION_ADJECTIVE.format(word=word)
    else:
        return []

    response = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=180,
        temperature=0.3,
    )
    
    print(response)
    raw_output = response.choices[0].message.content
    forms = parse_chatgpt_output(raw_output, '[', ']')
    forms = forms.lower()
    
    return set(json.loads(forms))

def generate_alternatives(word: str, type: str, language: str):
    if type == "verb":
        response = client.chat.completions.create(
            model=MODEL_SMART,
            messages=[{"role": "user", "content": INSTRUCTION_VERBS[language].format(word=word)}],
            max_tokens=550,
            temperature=0.25,
        )
        raw_output = response.choices[0].message.content
        forms = parse_chatgpt_output(raw_output, '{', '}')
        forms = forms.lower()
        dict = json.loads(forms)
        
        result_set = set()
        for value in dict.values():
            if isinstance(value, list):
                result_set.update(value)
            else:
                result_set.add(value)
        return result_set
        
    elif type == "noun":
        prompt = INSTRUCTION_NOUNS[language].format(word=word)
    elif type == "adjective":
        prompt = INSTRUCTION_ADJECTIVE[language].format(word=word)
    else:
        return []

    response = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=180,
        temperature=0.3,
    )
    
    raw_output = response.choices[0].message.content
    forms = parse_chatgpt_output(raw_output, '[', ']')
    forms = forms.lower()
    
    return set(json.loads(forms))

class WordVerdict(BaseModel):
    """Verdict from a separate check run AFTER root+forms are generated by
    the existing get_word_root() -> generate_alternatives() pipeline -- this
    does not replace or merge with that step, it reviews its output.

    The same verdict function is called from both places add_to_dictionary()
    can write a new row (bolt-on to an existing root, or a brand-new root),
    so `flagged` ends up driven by one identical check regardless of which
    of the Ozark-audit failure patterns (wrong-language root, homograph
    collision, conjugated-form-as-root, proper noun, malformed root,
    contaminated wordforms, ...) is actually present.

    definitely_not_valid is deliberately the inverse of a plain "valid"
    flag: the default is to trust get_word_root()/generate_alternatives(),
    and only override that trust when the reviewer is confident something
    is wrong -- not merely unsure. This avoids a bar so low that ordinary
    unusual-but-real Spanish (regionalisms, archaic forms, rare inflections)
    gets swept up as false positives.
    """
    definitely_not_valid: bool
    reason: str
    translation: str


def verify_and_translate(root: str, type: str, forms: list[str], language: str) -> WordVerdict:
    prompt = INSTRUCTION_VERIFY_NEW_WORD[language].format(
        root=root, type=type or "other", forms=", ".join(forms) or "(none)"
    )
    return parse_structured(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        schema_model=WordVerdict,
        max_tokens=300,
        temperature=0.2,
    )


def add_to_dictionary(word: str, source: str, language: str):
    try:
        word_root_info = get_word_root(word, language)
        if not word_root_info:
            print(f"Root info for {word} not found")
            raise ValueError(f"Could not determine root information for word '{word}'")

        # Try to identify the word id for the root
        try:
            root_id = identify_word_id(word_root_info["key"], language)
            # If we found an existing root ID, attach the surface token we
            # actually saw as a new wordform of it. Verify that single form
            # against the existing root before deciding whether to flag it --
            # a genuinely valid but previously-missing inflection shouldn't
            # be punished just because it collided with something.
            if root_id:
                flagged = True
                try:
                    verdict = verify_and_translate(word_root_info["key"], word_root_info.get("type"), [word], language)
                    flagged = verdict.definitely_not_valid
                except Exception as e:
                    print(f"Error verifying '{word}' against existing root '{word_root_info['key']}': {e}")
                print(f"Added '{word}' for {word_root_info['key']} (flagged={flagged})")
                return add_and_flag_wordform(word, root_id, language, flagged=flagged)
        except ValueError:
            # If the root doesn't exist, we'll continue with the normal flow to add it
            pass

        type = word_root_info.get("type")
        key = word_root_info.get("key")

        forms = generate_alternatives(key, type, language)

        flagged, translation = True, None
        try:
            verdict = verify_and_translate(key, type, list(forms), language)
            flagged, translation = verdict.definitely_not_valid, (verdict.translation or None)
        except Exception as e:
            print(f"Error verifying new entry '{key}': {e}")
            flagged = False  # unable to verify -- don't penalize; matches pre-verification behavior

        return save_to_supabase(key, forms, language, source, translation=translation, flagged=flagged)
    except Exception as e:
        print(f"Error adding word to dictionary: {e} ")
        return None

def parse(groups: List[str], source: str, language: str):
    """
    Process a list of text groups (tokens) and return a list of dictionaries.
    """
    result = []
    local_cache: Dict[str, Optional[int]] = {}
    missing_entries: List[Tuple[int, str, str]] = []

    # 1) First pass: immediate lookup or record as missing.
    for group in groups:
        if is_special_character(group) or not (word := group.strip()):
            result.append({"content": group})
            continue

        lw = word.lower()
        if lw in local_cache:
            entry = {"content": group}
            if local_cache[lw] is not None:
                entry["id"] = local_cache[lw]
            result.append(entry)
        else:
            try:
                wid = identify_word_id(lw, language)
                local_cache[lw] = wid
                result.append({"content": group, "id": wid})
            except ValueError:
                local_cache[lw] = None
                missing_entries.append((len(result), lw, group))
                result.append({"content": group})

    # 2) If any missing, batch-verify them in one LLM call:
    if missing_entries:
        missing_words = list(dict.fromkeys([e[1] for e in missing_entries]))
        # call the improved verifier
        try:
            bad = set(w.lower() for w in verify_language(missing_words, language))
        except Exception:
            bad = set()

        # map word → all result-indices
        idxs: Dict[str, List[int]] = {}
        for idx, lw, _ in missing_entries:
            idxs.setdefault(lw, []).append(idx)

        for lw in missing_words:
            if lw in bad:
                # leave as content only
                continue
            # otherwise add it permanently
            wid = add_to_dictionary(lw, source, language)
            for i in idxs[lw]:
                result[i]["id"] = wid
            local_cache[lw] = wid

    return result

def group_text(text: str) -> list:
    start_time = time.perf_counter()  # start time measurement
    special_chars = set(SPECIAL_CHARACTERS)
    result = [''.join(g) for _, g in groupby(text, key=lambda c: c in special_chars)]
    end_time = time.perf_counter()    # end time measurement
    print(f"group_text executed in {end_time - start_time:.6f} seconds")
    return result

async def get_missing_words(user_id: str, words: List[Dict], language: str) -> List[Dict]:
    
    word_ids = [word['id'] for word in words if 'id' in word and word['id'] is not None]
    word_ids = list(dict.fromkeys(word_ids))
    try:
        missing_words = get_missing_words_from_db(user_id, word_ids, language)
        return missing_words
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data from Supabase: {str(e)}")

class VideoAnalysis(BaseModel):
    conformsToLanguageCriteria: bool
    sensitivityRating: float
    targetAgeInterest: float  # Probability that a 21-30 year old would be interested
    likelyMusic: float
    intellectuality: float

def analyze_titles(channel, titles, language):
    """
    Analyze a list of video titles for language conformity, sensitivity, 21-30 age interest,
    likelihood of being music, and intellectuality.

    :param titles: List of video titles.
    :param language: The language to check against.
    :return: A structured VideoAnalysis object with the analysis results.
    """
    combined_titles = "\n".join(titles)
    
    prompt = f"""
    Analyze the following video titles of youtuber {channel} in terms of structured criteria:
    
    {{
        "conformsToLanguageCriteria": boolean,  # True if videos are maybe in {language}, false if they are definitely not. Consider that titles may only contain anglicisms.
        "sensitivityRating": float,             # Sensitivity (0-1 scale; 1 = very risky, risky meaning sensitive content related to drugs, sexual violence, prostitution, etc.).
        "targetAgeInterest": float,             # Probability (0-1) that a 21-30 year old would be interested.
        "likelyMusic": float,                   # Music likelihood (0-1 scale).
        "intellectuality": float                # Intellectual content rating (0-1 scale).
    }}

    Titles:
    \"\"\"{combined_titles}\"\"\"
    """

    try:
        # Was client.beta.chat.completions.parse(), which is an OpenAI-SDK
        # helper that assumes strict json_schema support. parse_structured()
        # does the same job portably: strict schema first, plain JSON mode as
        # a fallback, Pydantic validation either way.
        # MODEL_FAST, and reasoning off: this is a bounded classification, not
        # a judgement call. With reasoning on, the model spends the whole
        # max_tokens budget thinking and returns an empty body.
        return parse_structured(
            model=MODEL_FAST,
            messages=[{"role": "user", "content": prompt}],
            schema_model=VideoAnalysis,
            reasoning={"enabled": False},
            max_tokens=400,
            temperature=0.3,
        )

    except Exception as e:
        print(f"Error in analyzing titles: {e}")
        raise Exception("Could not complete title analysis")

def summarize_text(text: str) -> str:
    prompt = INSTRUCTION_SUMMARIZE.format(text=text)
    
    try:
        response = client.chat.completions.create(
            model=MODEL_FAST,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=25,
            temperature=0.3,
        )
        summary = response.choices[0].message.content.strip()
        # Remove any non-alphanumeric characters and replace spaces with underscores
        summary = ''.join(c for c in summary if c.isalnum() or c.isspace())
        summary = summary.replace(' ', '_').lower()
        return summary
    except Exception as e:
        print(f"Error summarizing text: {e}")
        return "untitled_article"



def parse_and_translate_word(word: str, language: str) -> Dict:
    # This used to map 'it'/'es' onto long names and everything else onto the
    # literal 'other'. Post-migration that turned a correct key into one the
    # ISO-keyed word_cache and INSTRUCTION_* tables no longer hold, so the
    # extension's word-lookup popup 500'd on a bare KeyError -- and the
    # except-ValueError fallback below would have written 'italian' into
    # words.language, which the words_language_is_iso CHECK now rejects.
    language = require_code(language)

    try:
        # First, try to identify the word in the database
        word_id = identify_word_id(word, language)
    except ValueError:
        # If the word is not in the database, add it
        word_id = add_to_dictionary(word, "MANUAL_TRANSLATION", language)
    
    translation = get_or_create_translation(word_id, language)
    root = find_root_by_wordform_id(word_id, language)
    
    return {
        "id": word_id,
        "root": root,
        "translation": translation
    }

# Takes a language name    
def translate_section(section: str, language: str) -> Dict:
    
    prompt = INSTRUCTION_TRANSLATE.format(text=section, language=language)
    
    response = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.3,
    )
    
    return response.choices[0].message.content

def verify_language(words: List[str], language: str) -> List[str]:
    """
    words: list of lowercase tokens to check
    returns: list of those tokens deemed NOT valid Spanish
    """
    # build bullet-list for prompt
    payload = "\n".join(f"- {w}" for w in words)

    system_msg = (
        "You are a meticulous Spanish lexicographer. "
        "Your job is to spot tokens that are NOT valid Spanish words."
    )
    user_msg = f"""
You are given a list of supposedly spanish words. Most of them are invalid.

For each token, consider them invalid if:
1. Not recognised by standard Spanish dictionaries (RAE or widely accepted regional).
2. Misspelling or nonsense string
3. Contains an article that should be removed
4. They're proper names, brands, acronyms, scientific/technical terms.
5. They're not real spanish words

Return **only** a complete, full JSON array of all the problematic tokens exactly as given, e.g.:
["elcarborundum", "rehue", "pesonas", "ceatividad"]
"""

    resp = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[
            {"role": "system",  "content": system_msg},
            {"role": "user",    "content": user_msg + "\n\n" + payload}
        ],
        max_tokens=3000,
        temperature=0.0,
    )
    out = resp.choices[0].message.content
    raw = parse_chatgpt_output(out, "[", "]")
    return json.loads(raw)

def generate_word_examples(
    words: List[str],
    language: str = "es",              # ← new parameter
) -> Dict[str, Dict[str, List[str]]]:
    """
    Generate two A1-A2 sentences (and highlight forms) *in the given language*
    for every word/phrase supplied.

    Parameters
    ----------
    words : List[str]
        Vocabulary items to illustrate.
    language : str
        Target language in which the examples should be written
        (e.g. "es", "en", "de", "french", ...).

    Returns
    -------
    dict
        {
          "word": {
            "sentences": [...],
            "highlights": [...]
          },
          ...
        }
    """
    if not words:
        return {}

    word_block = "\n".join(f"- {w}" for w in words)
    user_prompt = (
        f"You are given an array of words or phrases. For each item, write two "
        f"simple and interesting sentences in {language} that an A1–A2 learner can use to understand the words. " 
        "The sentences should provide enough context to make clear what the words mean"
        "Inflections, conjugations and pluralizations are encouraged but should ideally "
        "appear only in the second sentence. Also return the exact word forms that "
        "need to be highlighted.\n\n"
        "Return ONLY valid JSON with this shape:\n"
        '{ "word": { "sentences": ["...", "..."], "highlights": ["...", "..."] }, ... }\n\n'
        f"Words:\n{word_block}"
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL_FAST,
            messages=[{"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            max_tokens=1500,
            temperature=0.5,
        )

        msg = resp.choices[0].message
        if getattr(msg, "refusal", None):
            raise Exception(f"Model refused: {msg.refusal}")

        return json.loads(msg.content)

    except Exception:
        logger.exception("Error generating word examples")
        raise