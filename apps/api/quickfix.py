import urllib.parse
import json
from paths import data_file

def process_youtubers(json_path):
    # Read JSON data from the file
    with open(json_path, 'r', encoding='utf-8') as file:
        youtubers = json.load(file)
    
    for youtuber in youtubers:
        # Assume the URL structure includes "-<channel_id>" at the end
        encodedname = urllib.parse.quote(youtuber["Name"].replace(" ", "_"))
        url_parts = youtuber["ChannelLink"].replace(encodedname, "").split('-', 1)
        print(url_parts)
        if len(url_parts) > 1:
            channel_identifier = url_parts[-1]
            # Construct the new URL
            youtuber["ChannelLink"] = f"https://www.youtube.com/channel/{channel_identifier}"

    # Write the modified data back to a JSON file
    with open(json_path, 'w', encoding='utf-8') as file:
        json.dump(youtubers, file, indent=4)

# Usage
json_file_path = str(data_file('youtubers_spain.json'))
process_youtubers(json_file_path)