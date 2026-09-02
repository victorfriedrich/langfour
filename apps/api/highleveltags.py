import os
import json
from typing import List
from nlp_processing import get_high_level_tag
from paths import processed_dir

def update_files_with_high_level_tag(base_folder: str):
    """(Re)assign a high-level category to every *_processed.json file that
       (a) has no category yet, or (b) currently has 'Entertainment' or 'Other'.
    """
    for root, _, files in os.walk(base_folder):
        for file in files:
            if not file.endswith("_processed.json"):
                continue

            file_path = os.path.join(root, file)

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Skip files that already have a *different* category
                current_cat = data.get("category")
                if current_cat is not None:
                    continue

                title = data.get("title", "")
                tags = data.get("tags", [])

                high_level_tag = get_high_level_tag(title, tags)

                # Overwrite or insert the category
                data["category"] = high_level_tag

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                print(f"Updated {file_path}: {current_cat!r} → {high_level_tag!r}")

            except Exception as e:
                print(f"Error processing {file_path}: {e}")

# Usage
base_folder = str(processed_dir("es"))
update_files_with_high_level_tag(base_folder)
