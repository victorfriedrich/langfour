import json
from utils import is_special_character
from paths import data_file

def parse_frequency_list(file_path):
    # Use an ordered dictionary to maintain frequency order while tracking unique words
    unique_words = []
    seen_words = set()
    
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            # Split the line into parts
            parts = line.strip().split('\t')
            
            # Check if the line has the expected format
            if len(parts) == 3:
                # Extract the middle part (words)
                word_part = parts[1]
                
                # Skip special characters
                if is_special_character(word_part):
                    continue
                
                # Skip entries that contain spaces (multiple words)
                if ' ' in word_part:
                    continue
                
                # Convert to lowercase for consistency
                word_lower = word_part.lower()
                
                # Only add if we haven't seen this word before (case insensitive)
                if word_lower not in seen_words:
                    seen_words.add(word_lower)
                    unique_words.append(word_lower)
    
    return unique_words

def save_to_json(words, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False, indent=2)

# Usage
input_file = str(data_file('french.txt'))
output_file = str(data_file('french.json'))

word_list = parse_frequency_list(input_file)
save_to_json(word_list, output_file)

print(f"Parsed {len(word_list)} unique single words and saved to {output_file}")