import os
import json
from typing import List, Tuple, Dict
from paths import PROCESSED_DIR, processed_dir

# Global cache for categories
language_categories_cache: Dict[str, List[dict]] = {}

def load_categories_for_language(language: str) -> List[dict]:
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
        print(f"Error loading categories for {language}: {str(e)}")
        return []

def initialize_categories():
    supported_languages = ['es', 'it', 'de']  # Add all supported languages
    global language_categories_cache
    
    for language in supported_languages:
        print(language)
        language_categories_cache[language] = load_categories_for_language(language)

def load_documents(base_folder: str) -> Tuple[List[List[int]], List[str], List[str], List[str]]:
    """
    Load all documents from the base_folder. Extract category from each JSON file.
    Instead of loading full JSON content (which contains dictionaries for each word),
    we convert each document’s content into a list of word IDs (integers).
    
    Returns:
        documents (List[List[int]]): Each document is now a list of word IDs.
        filenames (List[str]): List of filenames corresponding to the documents.
        categories (List[str]): List of categories corresponding to each document.
        titles (List[str]): Display titles corresponding to each document.
    """
    documents = []
    filenames = []
    categories = []
    titles = []
    
    for filename in os.listdir(base_folder):
        if filename.endswith('.json') and not filename.endswith('.npz.meta.json'):
            file_path = os.path.join(base_folder, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    data = json.load(file)
                    
                    # Extract category (log error if not set)
                    category = data.get('category', 'Unknown')
                    if category == 'Unknown':
                        print(f"Error in category with file: {file_path}")
                    
                    # Extract content and convert to list of word IDs
                    content = data.get('content', [])
                    if isinstance(content, list):
                        # Each word should be a dict; extract its 'id'
                        word_ids = {word.get("id") for word in content if isinstance(word, dict) and word.get("id") is not None}
                        documents.append(sorted(word_ids))
                    else:
                        documents.append([])
                    
                    filenames.append(filename)
                    categories.append(category)
                    title = data.get('title', '')
                    titles.append(title if isinstance(title, str) else '')
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
    
    return documents, filenames, categories, titles

def get_category_icon(base_folder: str, category: str) -> str:
    icon_path = os.path.join(base_folder, 'icons', f'{category}.svg')  # Assuming icons are stored in a separate 'icons' folder
    if os.path.exists(icon_path):
        return icon_path
    return None

def get_categories_with_icons(base_folder: str = None) -> List[Dict[str, str]]:
    categories = []
    if base_folder is None:
        base_folder = str(PROCESSED_DIR)
    documents, _, categories_list, _ = load_documents(base_folder)
    unique_categories = set(categories_list)
    for category in unique_categories:
        icon = get_category_icon(base_folder, category)
        categories.append({"category": category, "icon": icon})
    return categories
