import csv
import io
import os
import sqlite3
import tempfile
import zipfile
import glob  # For flexible database search
import html
import re
from html.parser import HTMLParser
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Body, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Dict, Any

# Import functions from your modules
from database import identify_word_id, supabase  # Use supabase directly from database.py
from nlp_processing import identify_word_id, verify_language, get_word_root  # For processing missing words

router = APIRouter()
security = HTTPBearer()

# Narrower than languages.SUPPORTED_CODES on purpose: flashcard import has only
# ever accepted these two, and widening it is a product decision, not part of
# this migration. These are already ISO codes, so the three copies of the
# code -> long-name map that used to follow each check are simply gone.
ALLOWED_LANGUAGES = {"it", "es"}


class _AnkiHTMLTextExtractor(HTMLParser):
    """Turn Anki field HTML into text while retaining RemNote list structure."""

    BLOCK_TAGS = {"br", "div", "p", "li", "tr", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.list_depth = 0
        self.current_item = None
        self.list_items = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"ul", "ol"}:
            self.list_depth += 1
        if tag == "li":
            self.current_item = [self.list_depth, []]
        if tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "li" and self.current_item is not None:
            depth, item_parts = self.current_item
            item_text = _collapse_whitespace("".join(item_parts))
            if item_text:
                self.list_items.append((depth, item_text))
            self.current_item = None
        if tag in {"ul", "ol"}:
            self.list_depth = max(0, self.list_depth - 1)
        if tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self.current_item is not None:
            self.current_item[1].append(data)


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def clean_anki_field(value: str) -> str:
    """Strip formatting/media markup and unwrap RemNote's nested breadcrumbs.

    RemNote represents a card's path as nested HTML lists (for example,
    ``Spanish > Lesson 8 > llevar``).  In that case only the deepest list item
    is card content; importing the whole path makes the HTML and deck headings
    look like vocabulary.
    """
    if not value:
        return ""

    value = re.sub(r"\[sound:[^\]]+\]", " ", value, flags=re.IGNORECASE)
    parser = _AnkiHTMLTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        # HTMLParser is intentionally forgiving, but malformed exported HTML
        # should still degrade to plain text rather than aborting an import.
        return _collapse_whitespace(html.unescape(re.sub(r"<[^>]*>", " ", value)))

    if parser.list_items:
        deepest = max(depth for depth, _ in parser.list_items)
        # A nested list is RemNote's breadcrumb representation.  A regular,
        # single-level vocabulary list remains readable in full.
        if deepest > 1:
            leaves = [text for depth, text in parser.list_items if depth == deepest]
            return _collapse_whitespace(" / ".join(leaves))

    return _collapse_whitespace("".join(parser.parts))


def _extract_anki_pair(fields: List[str]) -> Dict[str, str]:
    """Return the vocabulary pair represented by an Anki note's fields.

    RemNote exports the prompt and answer of some concept cards together in a
    single field, separated by its rendered ``::`` delimiter.  Treating that
    entire field as the prompt sends the answer (for example, the German half
    of a Spanish/German card) through the Spanish dictionary lookup.  Prefer
    that explicit pair over Anki's remaining metadata fields.
    """
    for field in fields:
        sides = re.split(r"\s+::\s+", field, maxsplit=1)
        if len(sides) == 2:
            word, translation = (_collapse_whitespace(side) for side in sides)
            if word:
                return {"word": word, "translation": translation}

    word = fields[0] if fields else ""
    translation = fields[1] if len(fields) >= 2 else ""
    return {"word": word, "translation": translation}

# Authentication dependency
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        user = supabase.auth.get_user(token)
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

def extract_from_csv(file_bytes: bytes) -> List[Dict[str, str]]:
    """
    Extract word/translation pairs from a CSV file.
    Handles tab-delimited files without headers.
    """
    pairs = []
    try:
        # Try multiple encodings to handle potential BOM characters
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1']:
            try:
                decoded = file_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        # Split lines manually to ensure we don't miss the first line
        lines = decoded.strip().split('\n')
        for line in lines:
            if not line.strip():
                continue

            parts = line.split('\t')
            if len(parts) >= 2:
                word = parts[0].strip()
                translation = parts[1].strip()
                if word:
                    pairs.append({"word": word, "translation": translation})
            elif len(parts) == 1 and parts[0].strip():
                pairs.append({"word": parts[0].strip(), "translation": ""})

        print(f"Extracted {len(pairs)} pairs from CSV")
        for pair in pairs:
            print(f"Word: {pair['word']}, Translation: {pair['translation']}")
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"CSV parsing error: {str(e)}\n{error_details}")
        raise HTTPException(status_code=400, detail=f"CSV parsing error: {str(e)}")

    return pairs

def extract_from_apkg(file_bytes: bytes) -> List[Dict[str, str]]:
    """
    Extract word/translation pairs from an Anki deck (.apkg file).
    Handles both legacy and newer Anki formats (including compressed databases).

    Anki stores bidirectional cards as multiple cards pointing at one note.  We
    deliberately read the notes table, so a RemNote ``<>`` pair is imported
    once, in its original field order, instead of once per card direction.
    """
    pairs = []
    try:
        with tempfile.TemporaryDirectory() as tmpdirname:
            # Write the uploaded .apkg bytes to a temporary file.
            temp_apkg_path = os.path.join(tmpdirname, "deck.apkg")
            with open(temp_apkg_path, "wb") as temp_file:
                temp_file.write(file_bytes)

            # Extract all files from the .apkg (a zip archive)
            with zipfile.ZipFile(temp_apkg_path, "r") as zip_ref:
                zip_ref.extractall(tmpdirname)

            # Determine the collection database file.
            # Prefer newer Anki 2.1 formats if available.
            possible_names = ["collection.anki21", "collection.anki21b", "collection.anki2"]
            db_path = None
            for fname in possible_names:
                candidate = os.path.join(tmpdirname, fname)
                if os.path.exists(candidate):
                    db_path = candidate
                    break

            # If not found, try a glob search.
            if not db_path:
                db_files = glob.glob(os.path.join(tmpdirname, "collection.anki*"))
                if db_files:
                    db_path = db_files[0]
                else:
                    raise ValueError("Anki collection database not found in the .apkg file.")

            # If the file is a compressed Anki 2.1 deck (collection.anki21b), decompress it.
            if os.path.basename(db_path) == "collection.anki21b":
                try:
                    import zstandard as zstd
                except ImportError:
                    raise HTTPException(
                        status_code=500,
                        detail="zstandard library required for decompressing the Anki deck."
                    )
                with open(db_path, "rb") as comp_file:
                    compressed_data = comp_file.read()
                dctx = zstd.ZstdDecompressor()
                decompressed_data = dctx.decompress(compressed_data)
                # Save the decompressed data as a new SQLite file.
                decompressed_db_path = os.path.join(tmpdirname, "collection.anki21")
                with open(decompressed_db_path, "wb") as decompressed_file:
                    decompressed_file.write(decompressed_data)
                db_path = decompressed_db_path

            # Connect to the SQLite database.
            try:
                conn = sqlite3.connect(db_path)
            except sqlite3.OperationalError as e:
                if "newer version" in str(e).lower():
                    raise ValueError(
                        "The Anki deck requires a newer version of Anki than supported by the current extraction tool."
                    )
                else:
                    raise

            cursor = conn.cursor()
            cursor.execute("SELECT flds FROM notes")
            rows = cursor.fetchall()
            for (flds,) in rows:
                if not flds:
                    continue
                # Fields in a note are separated by the ASCII Unit Separator (0x1f)
                parts = [clean_anki_field(part) for part in flds.split("\x1f")]
                pair = _extract_anki_pair(parts)
                if pair["word"]:
                    pairs.append(pair)
            conn.close()
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        raise HTTPException(status_code=400, detail=f"Error processing Anki deck: {e}\n{error_details}")
    return pairs

@router.post("/check-words")
async def check_words(
    payload: Dict = Body(...),
    current_user: Dict = Depends(get_current_user)
):
    words = payload.get("words")
    language = payload.get("language")
    if not words or not isinstance(words, list):
        raise HTTPException(status_code=400, detail="Missing or invalid 'words' list.")
    if not language or language.lower() not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported or missing language code.")

    language = language.lower()

    identified = []
    missing = []
    for word in words:
        try:
            word_id = identify_word_id(word, language)
            # Optionally, fetch translation from your DB if you want to return it
            translation = ""  # TODO: fetch from DB if needed
            identified.append({"word": word, "id": word_id, "translation": translation})
        except ValueError:
            missing.append({"word": word})

    return {"identified": identified, "missing": missing}

@router.post("/upload")
async def upload_flashcards(
    file: UploadFile = File(...),
    language: str = Form("es"),
    source: str = Form("flashcards_upload"),
    current_user: Dict = Depends(get_current_user)
):
    """
    Securely uploads a flashcards file (.csv or .apkg), extracts word/translation pairs,
    and then quickly checks each word against the cache.

    Returns two lists:
      - "identified": objects with "word", "translation", and "id" for words found.
      - "missing": objects for words not found in the cache.
    """
    language = language.lower()
    if language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language code.")

    filename = file.filename.lower()
    file_bytes = await file.read()

    if filename.endswith(".csv"):
        pairs = extract_from_csv(file_bytes)
    elif filename.endswith(".apkg"):
        pairs = extract_from_apkg(file_bytes)
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload a .csv or .apkg file.")

    identified = []
    missing = []

    for pair in pairs:
        word = pair["word"]
        try:
            word_id = identify_word_id(word, language)
            identified.append({"word": word, "translation": pair.get("translation", ""), "id": word_id})
        except ValueError:
            missing.append({"word": word, "translation": pair.get("translation", "")})

    return {"identified": identified, "missing": missing}

@router.post("/process-missing")
async def process_missing_words(
    payload: Dict = Body(...),
    current_user: Dict = Depends(get_current_user)
):
    """
    Processes missing words (using add_to_dictionary) when the user chooses to add them.
    Expects a JSON payload with:
      - missing: a list of objects with "word" (and optionally "translation")
      - language: language code (variable)
      - source: a source identifier (e.g., "flashcards_upload")
      
    Returns a list of processed words with "word" and the newly created "id".
    """
    missing = payload.get("missing")
    language = payload.get("language")
    source = payload.get("source", "flashcards_upload")

    if not missing or not isinstance(missing, list):
        raise HTTPException(status_code=400, detail="Missing or invalid 'missing' words list.")
    if not language or language.lower() not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported or missing language code.")

    language = language.lower()

    processed = []

    # 1. Verify language validity for all words to save tokens.
    words_for_verification = []
    for item in missing:
        word = item.get("word")
        if not word:
            continue
        words_for_verification.append({"root": word.lower()})

    try:
        problematic_words = verify_language(words_for_verification, language)
        problematic_words = [w.lower() for w in problematic_words]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error verifying language: {e}")

    # 2. Process each word that passed language verification.
    for item in missing:
        word = item.get("word")
        if not word:
            continue

        if word.lower() in problematic_words:
            continue

        root_info = get_word_root(word, language)
        if not root_info or "key" not in root_info:
            continue

        try:
            word_id = identify_word_id(root_info["key"], language)
        except ValueError:
            continue

        if word_id:
            processed.append({"word": word, "id": word_id})

    return {"processed": processed}
