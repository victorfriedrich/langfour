import json
from nlp_processing import add_to_dictionary, identify_word_id
from database import initialize_cache
from paths import data_file

def convert_txt_to_json(file_path):
    words = []
    
    try:
        with open(file_path, 'r') as file:
            content = file.read()
            if content:
                print("File content:")
                print(content)
            else:
                print("File is empty")
    except Exception as e:
        print(f"Failed to read the file: {e}")

    
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        print(lines)
        # Start processing from the line after the header
        for line in lines[1:]:
            # Split the line by whitespace
            print(line)
            parts = line.split()
            if parts:
                # The word is in the second position after the order number
                word = parts[1]
                words.append(word)
    
    # Convert list of words to JSON format
    words_json = json.dumps(words, ensure_ascii=False, indent=2)
    
    # Optionally, you can write this JSON to a file
    with open(str(data_file('words10k.json')), 'w', encoding='utf-8') as json_file:
        json_file.write(words_json)
    
    return words_json

def load_json_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
    return data

def add_words_to_database_from_json(json_file_path, n):
    # Initialize the cache
    initialize_cache()
    
    # Load JSON data from file
    words = load_json_file(json_file_path)
    
    # Determine the start and end indices for the nth set of 100 words
    start_index = (n - 1) * 5000
    end_index = min(n * 5000, len(words))  # Ensure the end_index does not exceed the list length
    
    # Get the nth 100 words from the list
    words_to_add = words[start_index:end_index]
    
    # el hasta (829), tener?, bien, tan, sin, con, 
    
    # Add each word to the database
    for word in words_to_add:
        try:
            identify_word_id(word, "spanish")
        except ValueError:
            add_to_dictionary(word, "CREA", "spanish")
        # Optionally, you can store or log the word_id here for further processing
    
    return f"Added {len(words_to_add)} words to the database."

# Example usage
# TODO: Change dict["radice perfetta"] = dict["radice perfetta"].split()[1:]
json_file_path = str(data_file('spanish50k.json'))

# Add 250 words
result = add_words_to_database_from_json(json_file_path, 3)
print(result)

