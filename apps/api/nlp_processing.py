import json
import logging
import time
from itertools import groupby
from typing import Literal, get_args

from dotenv import load_dotenv
from fastapi import HTTPException
from pydantic import BaseModel

from database import (
    add_and_flag_wordform,
    find_root_by_wordform_id,
    get_missing_words_from_db,
    get_or_create_translation,
    identify_word_id,
    root_of,
    save_to_supabase,
)
from instructionmanager import (
    INSTRUCTION_ADJECTIVE,
    INSTRUCTION_CATEGORIZE,
    INSTRUCTION_FILTER_LANGUAGE,
    INSTRUCTION_NOUNS,
    INSTRUCTION_ROOT_FORM,
    INSTRUCTION_SUMMARIZE,
    INSTRUCTION_TRANSLATE,
    INSTRUCTION_VERBS,
    INSTRUCTION_VERIFY_LANGUAGE,
    INSTRUCTION_VERIFY_NEW_WORD,
)
from languages import require_code
from llm_client import client, parse_structured
from models import MODEL_FAST, MODEL_SMART
from utils import SPECIAL_CHARACTERS, is_special_character, parse_chatgpt_output

# A Literal rather than a plain list so the same definition can be both the
# validation rule and the JSON-schema enum sent to the model -- previously the
# enum was hand-written into a schema dict and then re-checked in Python.
Category = Literal[
    "Beauty & Fashion", "Health & Fitness", "Products & Tech", "Gaming", "Anime",
    "Movies", "Reactions & Commentary", "Challenges & Experiments", "Comedy",
    "Travel", "Documentaries", "Cooking", "Science",
    "Politics", "Finance", "Cars", "History", "Other"
]

VALID_CATEGORIES: list[str] = list(get_args(Category))

load_dotenv()

logger = logging.getLogger(__name__)


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
        raise Exception(f"Error filtering non-Spanish words: {e}") from e
    
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

    except Exception:
        logger.exception("Error generating tags for %r", title)
        return ["Failed"]

class HighLevelTag(BaseModel):
    category: Category


def get_high_level_tag(title: str, tags: list[str]) -> str | None:
    """The video's single high-level category, or None if the model could not
    be reached. None rather than a "Failed" sentinel because the only caller
    writes the result into *_processed.json and then skips any file that
    already has a category -- a sentinel would be written once and never
    retried."""
    prompt = (
        "Choose exactly one high-level category for this video.\n\n"
        f"Title: {title}\n"
        f"Tags: {', '.join(tags)}"
    )
    try:
        verdict = parse_structured(
            model=MODEL_FAST,
            messages=[{"role": "user", "content": prompt}],
            schema_model=HighLevelTag,
            reasoning={"enabled": False},
            max_tokens=200,
            temperature=0.2,
        )
    except Exception:
        logger.exception("Could not classify %r", title)
        return None
    return verdict.category


class WordRoot(BaseModel):
    """`key` becomes a dictionary headword and `type` selects which
    generate_alternatives() prompt runs, so both are load-bearing. They used
    to arrive as an unchecked dict: a response missing "key" surfaced as a
    KeyError deep inside add_to_dictionary(), and a wrong-shaped one could
    reach identify_word_id() and the database."""

    type: Literal["verb", "noun", "adjective", "other"]
    key: str


def get_word_root(word: str, language: str) -> dict | None:
    prompt = INSTRUCTION_ROOT_FORM[language].format(word=word)
    try:
        return parse_structured(
            model=MODEL_SMART,
            messages=[{"role": "user", "content": prompt}],
            schema_model=WordRoot,
            max_tokens=200,
            temperature=0.3,
        ).model_dump()
    except Exception:
        logger.exception("Error finding root form for %r", word)
        return None

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


def _review(root: str, type: str | None, forms: list[str],
            language: str) -> tuple[bool, str | None]:
    """(flagged, translation) for a candidate entry.

    The two callers below used to disagree about a failed review: the
    bolt-on-to-an-existing-root path left flagged=True, the new-root path
    reset it to False. Identical verifier outages therefore produced opposite
    records. Flagging wins, because a flagged row is reviewable and an
    unflagged bad row is invisible.
    """
    try:
        verdict = verify_and_translate(root, type, forms, language)
        return verdict.definitely_not_valid, (verdict.translation or None)
    except Exception:
        logger.exception("Could not verify %r", root)
        return True, None


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
                # Verify against the root that was RESOLVED, not the one
                # proposed: identify_word_id() falls through to the wordform
                # cache, so a homograph lands the write on a different row than
                # the key implies -- ("hecho", ["hecha"]) looked valid while the
                # write went to root "the fact".
                resolved = root_of(root_id) or word_root_info["key"]
                flagged, _ = _review(
                    resolved, word_root_info.get("type"), [word], language
                )
                print(f"Added '{word}' for {resolved} (flagged={flagged})")
                return add_and_flag_wordform(word, root_id, language, flagged=flagged)
        except ValueError:
            # If the root doesn't exist, we'll continue with the normal flow to add it
            pass

        type = word_root_info.get("type")
        key = word_root_info.get("key")

        forms = generate_alternatives(key, type, language)

        flagged, translation = _review(key, type, list(forms), language)

        return save_to_supabase(key, forms, language, source, translation=translation, flagged=flagged)
    except Exception as e:
        print(f"Error adding word to dictionary: {e} ")
        return None

def parse(groups: list[str], source: str, language: str):
    """
    Process a list of text groups (tokens) and return a list of dictionaries.
    """
    result = []
    local_cache: dict[str, int | None] = {}
    missing_entries: list[tuple[int, str, str]] = []

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
            bad = {w.lower() for w in verify_language(missing_words, language)}
        except Exception:
            # This used to fall back to an empty set, i.e. "nothing is
            # invalid", so an outage wrote every unknown token into the
            # dictionary unverified and permanently. Leaving them as plain
            # content is recoverable -- the next parse of the same text
            # retries them.
            logger.exception("Language check failed; leaving %d words unresolved",
                             len(missing_words))
            return result

        # map word → all result-indices
        idxs: dict[str, list[int]] = {}
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

async def get_missing_words(user_id: str, words: list[dict], language: str) -> list[dict]:
    
    word_ids = [word['id'] for word in words if 'id' in word and word['id'] is not None]
    word_ids = list(dict.fromkeys(word_ids))
    try:
        missing_words = get_missing_words_from_db(user_id, word_ids, language)
        return missing_words
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data from Supabase: {e!s}") from e

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



def parse_and_translate_word(word: str, language: str) -> dict:
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
def translate_section(section: str, language: str) -> dict:
    
    prompt = INSTRUCTION_TRANSLATE.format(text=section, language=language)
    
    response = client.chat.completions.create(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.3,
    )
    
    return response.choices[0].message.content

class InvalidWords(BaseModel):
    invalid: list[str]


def verify_language(words: list[str], language: str) -> list[str]:
    """Of `words`, the ones that are not valid words of `language`.

    The criteria live in INSTRUCTION_VERIFY_LANGUAGE, which has always had a
    per-language entry -- this function previously ignored its `language`
    argument entirely and inlined a Spanish-only prompt, so German, French and
    Italian tokens were judged by a "meticulous Spanish lexicographer".
    """
    if not words:
        return []

    code = require_code(language)
    payload = "\n".join(f"- {w}" for w in words)
    prompt = (
        INSTRUCTION_VERIFY_LANGUAGE[code].format(word_list=payload)
        # The instruction bodies ask for a bare JSON array; the schema below
        # needs an object, so name the wrapper here rather than making four
        # prompt files agree about a detail of the transport.
        + '\n\nReturn the result as {"invalid": ["word1", "word2", ...]}.'
    )

    return parse_structured(
        model=MODEL_SMART,
        messages=[{"role": "user", "content": prompt}],
        schema_model=InvalidWords,
        max_tokens=3000,
        temperature=0.0,
    ).invalid


def generate_word_examples(
    words: list[str],
    language: str = "es",              # ← new parameter
) -> dict[str, dict[str, list[str]]]:
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