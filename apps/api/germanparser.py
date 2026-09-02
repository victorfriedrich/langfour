import json
from paths import data_file

def parse_frequency_list(file_path):
    words = []
    
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            # Split the line into parts
            parts = line.strip().split('\t')
            
            # Check if the line has the expected format
            if len(parts) == 3:
                # Extract the middle part (words)
                word_part = parts[1]
                
                # If the word_part contains spaces, split it into multiple words
                if ' ' in word_part:
                    words.extend(word_part.split())
                else:
                    words.append(word_part)

    return words

def save_to_json(words, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False, indent=2)

# Usage
input_file = str(data_file('german.txt'))
output_file = str(data_file('words.json'))

word_list = parse_frequency_list(input_file)
save_to_json(word_list, output_file)

print(f"Parsed {len(word_list)} words and saved to {output_file}")