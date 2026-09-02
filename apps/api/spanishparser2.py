import json
from paths import data_file

def parse_frequency_list(file_path):
    words = []
    
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            parts = line.strip().split('\t')
            words.append(parts[0])

    return words

def save_to_json(words, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False, indent=2)

# Usage
input_file = str(data_file('spanish50k.txt'))
output_file = str(data_file('spanish50k.json'))

word_list = parse_frequency_list(input_file)
save_to_json(word_list, output_file)

print(f"Parsed {len(word_list)} words and saved to {output_file}")