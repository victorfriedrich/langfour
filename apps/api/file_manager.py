import json
import os

import numpy as np

from paths import PROCESSED_DIR, processed_dir

# Global cache for categories
language_categories_cache: dict[str, list[dict]] = {}

def load_categories_for_language(language: str) -> list[dict]:
    if language == 'it':
        return [
            {"category": 'Documentaries', "icon": None},
            {"category": 'Entertainment', "icon": None},
            {"category": 'Cooking', "icon": None},
            {"category": 'Travel', "icon": None},
            {"category": 'Politics', "icon": None},
            {"category": 'Science', "icon": None},
            {"category": 'Cars', "icon": None},
            {"category": 'Other', "icon": None}
        ]
    
    base = str(processed_dir(language))
    try:
        categories = get_categories_with_icons(base)
        print(language)
        print(categories)
        return categories
    except Exception as e:
        print(f"Error loading categories for {language}: {e!s}")
        return []

def initialize_categories():
    supported_languages = ['es', 'it', 'de']  # Add all supported languages
    global language_categories_cache
    
    for language in supported_languages:
        print(language)
        language_categories_cache[language] = load_categories_for_language(language)

Document = tuple[np.ndarray, np.ndarray]


def video_details(data: dict) -> tuple[str, int | None]:
    """A transcript's channel name and length in seconds, as videoparsing
    stores them ("creator", "length"): '' and None when missing."""
    creator = data.get("creator")
    length = data.get("length")
    return (creator.strip() if isinstance(creator, str) else "",
            int(length) if isinstance(length, (int, float)) and length > 0 else None)


def load_documents(base_folder: str) -> tuple[list[Document], list[str], list[str], list[str],
                                              list[str], list[int | None]]:
    """
    Load all documents from the base_folder. Extract category from each JSON file.
    Instead of loading full JSON content (which contains dictionaries for each word),
    each document becomes its distinct word ids and how often each is spoken.

    Returns:
        documents: per document, (word ids ascending, int32; times spoken, int32).
            The counts are what make coverage a share of the words heard; a set
            of ids counted "que" said 80 times once.
        filenames (List[str]): List of filenames corresponding to the documents.
        categories (List[str]): List of categories corresponding to each document.
        titles (List[str]): Display titles corresponding to each document.
        creators: each document's channel name, '' when unknown.
        lengths: each document's length in seconds, None when unknown.
    """
    documents = []
    filenames = []
    categories = []
    titles = []
    creators = []
    lengths = []

    for filename in os.listdir(base_folder):
        if filename.endswith('.json') and not filename.endswith('.npz.meta.json'):
            file_path = os.path.join(base_folder, filename)
            try:
                with open(file_path, encoding='utf-8') as file:
                    data = json.load(file)
                    
                    # Extract category (log error if not set)
                    category = data.get('category', 'Unknown')
                    if category == 'Unknown':
                        print(f"Error in category with file: {file_path}")
                    
                    # Extract content and convert to list of word IDs
                    content = data.get('content', [])
                    if not isinstance(content, list):
                        content = []
                    # Each word should be a dict; extract its 'id'
                    spoken = np.fromiter(
                        (word["id"] for word in content
                         if isinstance(word, dict) and word.get("id") is not None),
                        dtype=np.int64,
                    )
                    word_ids, counts = np.unique(spoken, return_counts=True)
                    documents.append((word_ids.astype(np.int32), counts.astype(np.int32)))
                    
                    filenames.append(filename)
                    categories.append(category)
                    title = data.get('title', '')
                    titles.append(title if isinstance(title, str) else '')
                    creator, length = video_details(data)
                    creators.append(creator)
                    lengths.append(length)
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
    
    return documents, filenames, categories, titles, creators, lengths

def get_category_icon(base_folder: str, category: str) -> str:
    icon_path = os.path.join(base_folder, 'icons', f'{category}.svg')  # Assuming icons are stored in a separate 'icons' folder
    if os.path.exists(icon_path):
        return icon_path
    return None

def get_categories_with_icons(base_folder: str | None = None) -> list[dict[str, str]]:
    categories = []
    if base_folder is None:
        base_folder = str(PROCESSED_DIR)
    _documents, _, categories_list, *_ = load_documents(base_folder)
    unique_categories = set(categories_list)
    for category in unique_categories:
        icon = get_category_icon(base_folder, category)
        categories.append({"category": category, "icon": icon})
    return categories
