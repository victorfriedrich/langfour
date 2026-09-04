import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from paths import data_file

# Threshold for minimum percentage of subscribers viewing videos
MIN_VIEWS_PER_SUBSCRIBER_PERCENTAGE = 0.01  # 1%

# Number of videos initially added per youtuber
TOP_VIDEO_COUNT = 15

# Video scoring settings
MAX_PERMITTED_LENGTH = 33
VIEW_BIAS = 0.9

FILEPATH = str(data_file("yt_fr.json"))

def bypass_consent(driver):
    # Wait for the "Alle ablehnen" button to be clickable
    consent_button = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='Alle ablehnen']"))
    )
    # Click the button
    consent_button.click()
    time.sleep(1)

# Read the input data from a JSON file
def read_input_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

# Write the output data back to the JSON file
def write_output_file(file_path, data):
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

# Function to convert German formatted view count to a number
def parse_view_count(view_count_text):
    cleaned_text = view_count_text.replace(' Aufrufe', '').replace(',', '.').strip()
    if 'Mio.' in cleaned_text:
        return int(float(cleaned_text.replace('Mio.', '').strip()) * 1000000)
    elif cleaned_text:
        return int(cleaned_text.replace('.', ''))
    return 0

# Function to convert video length (e.g., "12:34" or "1:23:45") to minutes
def parse_video_length(length_text):
    parts = length_text.split(':')
    if len(parts) == 2:  # MM:SS
        return int(parts[0])
    elif len(parts) == 3:  # HH:MM:SS
        return int(parts[0]) * 60 + int(parts[1])
    return 0

# Function to normalize a value between a min and max
def normalize(value, min_val, max_val):
    if value <= min_val:
        return 0
    if value >= max_val:
        return 1
    return (value - min_val) / (max_val - min_val)

# Function to calculate the score based on normalized length and views
def calculate_score(video, min_views, max_views):
    min_length = 8  # Minimum preferred video length in minutes
    max_length = 25  # Maximum preferred video length in minutes
    normalized_length = 1 - normalize(video['length'], min_length, min(max_length, MAX_PERMITTED_LENGTH))
    normalized_views = normalize(video['views'], min_views * 1.1, max_views)
    score = (1-VIEW_BIAS) * normalized_length + VIEW_BIAS * normalized_views
    return score

# Function to check if a YouTuber has sufficient views per subscriber
def has_sufficient_views_per_subscriber(views, subscribers):
    return views >= MIN_VIEWS_PER_SUBSCRIBER_PERCENTAGE * subscribers

def process_videos(videos):
    filtered_videos = [video for video in videos if video['length'] <= MAX_PERMITTED_LENGTH]
    if not filtered_videos:
        return []
    min_views = min(video['views'] for video in filtered_videos)
    max_views = max(video['views'] for video in filtered_videos)
    scored_videos = [
        {**video, 'score': calculate_score(video, min_views, max_views)}
        for video in filtered_videos
    ]
    top_videos = sorted(scored_videos, key=lambda v: v['score'], reverse=True)[:TOP_VIDEO_COUNT]
    return top_videos

def scroll_to_end(driver):
    driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
    time.sleep(4)

def extract_videos_data(driver):
    video_elements = driver.find_elements(By.CSS_SELECTOR, '#contents ytd-rich-item-renderer')
    videos_data = []
    for video_element in video_elements:
        try:
            video_link_element = video_element.find_element(By.CSS_SELECTOR, 'a#thumbnail')
            video_id = video_link_element.get_attribute('href').split('v=')[-1]
            
            video_title_element = video_element.find_element(By.CSS_SELECTOR, 'a#video-title-link')
            video_title = video_title_element.get_attribute('title').strip()
            
            view_count_element = video_element.find_elements(By.CSS_SELECTOR, '#metadata-line span.inline-metadata-item')[0]
            view_count_text = view_count_element.text
            views = parse_view_count(view_count_text)
            
            video_length_element = video_element.find_element(By.CSS_SELECTOR, 'span.ytd-thumbnail-overlay-time-status-renderer')
            video_length_text = video_length_element.get_attribute("innerText").strip()
            length = parse_video_length(video_length_text)
            
            if video_id and video_title and views is not None and length is not None:
                videos_data.append({
                    'id': video_id,
                    'title': video_title,
                    'views': views,
                    'length': length,
                })

        except Exception as e:
            print("Error extracting video data: ", e)

    return videos_data

def main(input_file, output_file):
    creator_list = read_input_file(input_file)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    driver.get("https://www.youtube.com/channel/UC0GCEXXncFMqGWkQfG28eMg")
    bypass_consent(driver)
    
    for creator in creator_list:
        if "Failreason" in creator:
            continue
        if "Videos" in creator and len(creator["Videos"]) >= 10:
            continue
        
        channel_url = creator["ChannelLink"] + "/videos"
        driver.get(channel_url)
        
        time.sleep(5)
        
        for _ in range(2):
            scroll_to_end(driver)
        
        videos_data = extract_videos_data(driver)
        
        # Calculate average views per video
        total_views = sum(video['views'] for video in videos_data)
        avg_views = total_views / len(videos_data) if videos_data else 0

        # Check if views per subscriber threshold is met
        if not has_sufficient_views_per_subscriber(avg_views, creator['Subscribers']):
            creator["Failreason"] = f"ViewsPerSub {round(avg_views)}"
            print(f"Skipping creator {creator.get('Name', 'unknown')} due to low views per subscriber {(avg_views)}")
        else:
            creator["Videos"] = process_videos(videos_data)

        write_output_file(output_file, creator_list)
        print(f"Data for creator {creator.get('Name', 'unknown')} written to output.")

    driver.quit()
    print("Scraping complete. Final results written to: ", output_file)

main(FILEPATH, FILEPATH)
