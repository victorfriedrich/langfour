import json
from paths import ARTICLES_DIR

def extract_ids_from_file(file_path):
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            ids = [item['id'] for item in data['content'] if 'id' in item]
            return ids
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return []
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in file {file_path}")
        return []
    except KeyError:
        print(f"Error: 'content' key not found in JSON from {file_path}")
        return []

# Example usage:
file_path = str(ARTICLES_DIR / 'parole_italiane.json')
result = extract_ids_from_file(file_path)
print(list(set(result)))