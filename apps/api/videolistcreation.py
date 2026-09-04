from nlp_processing import analyze_titles
import time
import json
import os
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
import requests
import numpy as np
import pandas as pd
from paths import data_file

# Load the environment variables from the .env file
load_dotenv()
API_KEY = os.getenv('YOUTUBE_API_KEY')

def get_video_details(video_id):
    url_video_stats = f'https://www.googleapis.com/youtube/v3/videos?id={video_id}&part=statistics&key={API_KEY}'
    response_video_stats = requests.get(url_video_stats).json()
    print(response_video_stats)
    # Extract view, like, and comment counts
    view_count = int(response_video_stats['items'][0]['statistics']['viewCount'])
    like_count = int(response_video_stats['items'][0]['statistics'].get('likeCount', 0))
    comment_count = int(response_video_stats['items'][0]['statistics'].get('commentCount', 0))

    return view_count, like_count, comment_count

def update_likes_comments(filename):
    # Load JSON data from the file
    with open(filename, 'r', encoding='utf-8') as file:
        json_data = json.load(file)

    for channel_index, channel in enumerate(json_data):
        updated_video = False
        if 'Videos' not in channel:
            continue
        for video in channel['Videos']:
            # Skip videos that already have like/comment data
            if 'Likes' in video and 'Comments' in video:
                continue

            try:
                view_count, like_count, comment_count = get_video_details(video['id'])
                # Abort if all returned counts are zero
                if view_count == 0 and like_count == 0 and comment_count == 0:
                    print(f"Aborting: All data returned as zero for video ID {video['id']}.")
                    return

                # Update video details in the JSON data
                video['Views'] = view_count
                video['Likes'] = like_count
                video['Comments'] = comment_count
                updated_video = True

            except Exception as e:
                print(f"Error encountered for video {video['id']}: {e}")
                continue  # Skip this video and continue with the next
        
        if not updated_video:
            continue
        
        # Save progress after each channel to minimize data loss
        try:
            temp_filename = f"{filename}.tmp"
            with open(temp_filename, 'w', encoding='utf-8') as temp_file:
                json.dump(json_data, temp_file, indent=2, ensure_ascii=False)
            os.replace(temp_filename, filename)
            print(f"Progress saved after processing channel {channel.get('Name', channel_index)}.")
        except Exception as e:
            print(f"Failed to save progress: {e}")
            # Decide whether to continue or abort; here we continue
            continue

def calculate_avg_engagement(filename):
    # Load JSON data from the file
    with open(filename, 'r') as file:
        json_data = json.load(file)
    
    for channel in json_data:
        # Only process channels with videos
        if 'Videos' in channel:
            total_views = 0
            total_likes = 0
            total_comments = 0

            # Sum views, likes, and comments for each video
            for video in channel['Videos']:
                views = video.get('Views', 0)
                likes = video.get('Likes', 0)
                comments = video.get('Comments', 0)
                
                total_views += views
                total_likes += likes
                total_comments += comments

            # Calculate averages if there are any views
            if total_views > 0:
                avg_engagement_rate = (total_likes + total_comments) / total_views
                avg_views_per_sub = total_views / channel['Subscribers'] if channel.get('Subscribers') else 0
            else:
                avg_engagement_rate = 0
                avg_views_per_sub = 0

            # Add the calculated attributes to the channel
            channel['AvgEngagementRate'] = avg_engagement_rate
            channel['AvgViewsPerSub'] = avg_views_per_sub

    # Save the updated JSON data back to the file
    with open(filename, 'w') as file:
        json.dump(json_data, file, indent=2)

_API_KEY_IN_URL = re.compile(r'([?&]key=)[^&\s"\'<>]+')


def redact_api_key(text: str) -> str:
    """Strip the API key out of text before it reaches a data file.

    A googleapiclient HttpError stringifies to the whole request URL, key
    and all, so writing str(e) into a record that gets committed is enough
    to publish the key. Redact at the write site, not at review time.
    """
    return _API_KEY_IN_URL.sub(r'\1REDACTED', text)


def fetch_youtube_channel_links(file_path: str):
    # Load API key & build service
    API_KEY = os.getenv('YOUTUBE_API_KEY')
    if not API_KEY:
        raise RuntimeError("Set YOUTUBE_API_KEY in your environment")
    youtube = build('youtube', 'v3', developerKey=API_KEY)

    # Load existing data
    with open(file_path, 'r') as f:
        youtubers = json.load(f)

    updated = False

    for y in youtubers:
        # Only fix those with the specific failreason
        if y.get('Failreason') != 'ViewsPerSub 0':
            continue

        name = y.get('Name')
        try:
            # Search for their channel by name
            sr = (youtube.search()
                      .list(q=name, part='id', maxResults=1, type='channel')
                      .execute())
            items = sr.get('items', [])
            if items:
                chan_id = items[0]['id']['channelId']
                y['ChannelLink'] = f"https://www.youtube.com/channel/{chan_id}"
                y.pop('Failreason', None)
            else:
                # still not found
                y['Failreason'] = 'no_url_found'
        except Exception as e:
            y['Failreason'] = f'api_error: {redact_api_key(str(e))}'

        updated = True
        time.sleep(0.1)  # back off a bit

    # Write back once if we changed anything
    if updated:
        with open(file_path, 'w') as f:
            json.dump(youtubers, f, indent=2)
        print("Updated ChannelLink for entries with ViewsPerSub 0.")
    else:
        print("No entries with ViewsPerSub 0 found; nothing changed.")

# Function to convert subscriber count from string to a number
def convert_subscribers(subscriber_str):
    if subscriber_str.endswith('M'):
        return int(float(subscriber_str[:-1]) * 1_000_000)
    elif subscriber_str.endswith('K'):
        return int(float(subscriber_str[:-1]) * 1_000)
    else:
        return int(subscriber_str)

# Function to process the JSON data and save the result to a new file
def process_youtubers_data(input_file, output_file):
    # Load JSON data from a file
    with open(input_file, 'r', encoding='utf-8') as file:
        json_data = json.load(file)

    # Process JSON data
    result = []
    for item in json_data:
        name = item['Name']
        channel_id = item['ChannelLink'].split("-")[-1]
        subscribers = int(item['Subscribers'])
        channel_link = f"https://www.youtube.com/channel/{channel_id}"
        result.append({'Name': name, 'Subscribers': subscribers, 'ChannelLink': channel_link})

    # Save the result to a new file
    with open(output_file, 'w', encoding='utf-8') as file:
        json.dump(result, file, indent=2, ensure_ascii=False)

# Example of calling the function
#process_youtubers_data(str(data_file('youtubers_france.json')), str(data_file('yt_fr.json')))
#fetch_youtube_channel_links("yt_fr.json")

"""
Javascript-Code, since this only works for authenticated accounts
const youtubers = [];

    document.querySelectorAll('tr').forEach((element) => {
        try {
            const rankTd = element.querySelector('td.fs-5.fw-bold');
            const rank = rankTd ? rankTd.textContent.trim() : 'N/A';

            const nameDiv = element.querySelector('div.mb-1.fw-bold');
            const name = nameDiv ? nameDiv.textContent.trim() : 'N/A';
            
            const channelLinkTag = element.querySelector('a.link');
            const channelLink = channelLinkTag ? channelLinkTag.href : 'N/A';

            const subscribersTd = element.querySelectorAll('td')[2];
            const subscribersDiv = subscribersTd ? subscribersTd.querySelector('div') : null;
            const subscribers = subscribersDiv ? subscribersDiv.textContent.trim() : 'N/A';
            
            const countryDiv = element.querySelector('div.country');
            const country = countryDiv ? countryDiv.textContent.trim() : 'N/A';

            if (rank !== 'N/A') { // Ensuring we don't push empty or header rows
                youtubers.push({
                    Rank: rank,
                    Name: name,
                    Channel_Link: channelLink,
                    Subscribers: subscribers,
                    Country: country
                });
            }
        } catch (error) {
            console.error(`Error processing row: ${error.message}`);
        }
    });

    console.log(youtubers);

"""

def process_channels(file_path):
    with open(file_path, 'r') as file:
        channels = json.load(file)
    
    for channel in channels:
        if channel.get("Failreason") == "ViewsPerSub 0":
            # Remove Failreason
            channel.pop("Failreason", None)
            # Update ChannelLink
            formatted_name = channel["Name"].replace(" ", "")
            channel["ChannelLink"] = f"https://www.youtube.com/@{formatted_name}"
    
    # Save the modified data back to the file
    with open(file_path, 'w') as file:
        json.dump(channels, file, indent=4)

def calculate_dislikes(file_path):
    if not os.path.exists(file_path):
        print("Input file does not exist.")
        return
    
    # Load the JSON data from the file
    with open(file_path, 'r') as file:
        data = json.load(file)
    
    iteration = 0
    
    for channel in data:
        total_ratio, count = 0, 0
        for video in channel.get("Videos", []):
            if "Likes" in video and "Comments" in video and "Dislikes" not in video:
                video_id = video["id"]
                response = requests.get(f"https://returnyoutubedislikeapi.com/votes?videoId={video_id}")
                time.sleep(1.2)
                
                if response.status_code == 200:
                    dislike_data = response.json()
                    api_views = dislike_data.get("viewCount", 0)
                    json_views = video.get("Views", 0)

                    # Check if API views are within 90% of the JSON views (both directions)
                    if json_views * 0.8 <= api_views <= json_views * 1.2:
                        video["Dislikes"] = dislike_data.get("dislikes", 0)
                        # Calculate the like/dislike ratio for each video
                        like_dislike_ratio = video["Likes"] / (video["Dislikes"] or 1)  # Avoid division by zero
                        total_ratio += like_dislike_ratio
                        count += 1
                    else:
                        print(f"Skipping video ID {video_id}: API views {api_views} are not within 80% of JSON views {json_views}.")
                else:
                    print(f"Failed to retrieve data for video ID {video_id}")
        
        # Calculate and add the average like/dislike ratio to the creator's profile
        if count > 0:
            channel["AvgLikeDislikeRatio"] = total_ratio / count

        iteration += 1
        print(iteration)
        # Save the modified JSON data back to the same file
        if iteration > 4:
            with open(file_path, "w") as file:
                json.dump(data, file, indent=2)
            print(f"Updated data saved to {file_path}")
            iteration = 0
    
        
def calculate_youtuber_rankings(json_file_path, engagement_weight, views_per_sub_weight, subscriber_weight, top_n, output_file_path):
    # Load the JSON data
    with open(json_file_path, 'r') as file:
        data = json.load(file)

    # Filter valid entries with the required metrics
    valid_youtubers = [
        {
            "Name": yt["Name"],
            "Subscribers": yt["Subscribers"],
            "ChannelLink": yt["ChannelLink"],
            "AvgEngagementRate": yt.get("AvgEngagementRate"),
            "AvgViewsPerSub": yt.get("AvgViewsPerSub")
        }
        for yt in data
        if "Subscribers" in yt and yt.get("AvgEngagementRate") is not None and yt.get("AvgViewsPerSub") is not None
    ]

    # Convert to DataFrame for easier calculations
    df = pd.DataFrame(valid_youtubers)
    
    # Calculate percentiles
    df['EngagementPercentile'] = df['AvgEngagementRate'].rank(pct=True)
    df['ViewsPerSubPercentile'] = df['AvgViewsPerSub'].rank(pct=True)
    df['SubscribersPercentile'] = df['Subscribers'].rank(pct=True)

    # Calculate weighted ranking score
    df['TotalRankingScore'] = (
        df['EngagementPercentile'] * engagement_weight +
        df['ViewsPerSubPercentile'] * views_per_sub_weight +
        df['SubscribersPercentile'] * subscriber_weight
    )

    # Select the top n YouTubers based on TotalRankingScore
    top_youtubers = df.nlargest(top_n, 'TotalRankingScore')

    # Prepare data for output
    output_data = top_youtubers[["Name", "Subscribers", "ChannelLink"]].to_dict(orient="records")

    # Save the results to a new JSON file
    with open(output_file_path, 'w') as outfile:
        json.dump(output_data, outfile, indent=4)

    print(f"Top {top_n} YouTubers saved to {output_file_path}")

def weighted_rankings(json_file_path, weights, top_n, output_file_path):
    """
    weights should be a dictionary with format:
    {
        "metrics": {
            "AvgEngagementRate": {"weight": 0.3, "reverse": False},
            "AvgViewsPerSub": {"weight": 0.2, "reverse": False},
            "Subscribers": {"weight": 0.1, "reverse": False}
        },
        "title_analysis": {
            "conformsToLanguageCriteria": {"weight": 0.1, "reverse": False},
            "sensitivityRating": {"weight": 0.1, "reverse": True},
            "targetAgeInterest": {"weight": 0.1, "reverse": False},
            "likelyMusic": {"weight": 0.05, "reverse": False},
            "intellectuality": {"weight": 0.05, "reverse": False}
        }
    }
    """
    
    # Load the JSON data
    with open(json_file_path, 'r') as file:
        data = json.load(file)

    # Filter valid entries
    valid_youtubers = []
    for yt in data:
        if all(metric in yt for metric in weights["metrics"]) and "TitleAnalysis" in yt:
            youtuber_data = {
                "Name": yt["Name"],
                "Subscribers": yt["Subscribers"],
                "ChannelLink": yt["ChannelLink"],
                "Videos": yt["Videos"]
            }
            
            # Add metrics
            for metric in weights["metrics"]:
                youtuber_data[metric] = yt[metric]
            
            # Add title analysis metrics
            for title_metric in weights["title_analysis"]:
                youtuber_data[f"title_{title_metric}"] = yt["TitleAnalysis"][title_metric]
            
            if youtuber_data["title_likelyMusic"] < 0.7:
                valid_youtubers.append(youtuber_data)

    # Convert to DataFrame
    df = pd.DataFrame(valid_youtubers)
    
    # Calculate weighted score
    total_score = 0
    
    # Process regular metrics
    for metric, config in weights["metrics"].items():
        percentile = df[metric].rank(pct=True, ascending=config["reverse"])
        total_score += percentile * config["weight"]
    
    # Process title analysis metrics
    for title_metric, config in weights["title_analysis"].items():
        column_name = f"title_{title_metric}"
        percentile = df[column_name].rank(pct=True, ascending=config["reverse"])
        total_score += percentile * config["weight"]
    
    df['TotalRankingScore'] = total_score

    # Select top n YouTubers
    top_youtubers = df.nlargest(top_n, 'TotalRankingScore')

    # Prepare output data
    output_data = top_youtubers.to_dict(orient="records")

    # Save results
    with open(output_file_path, 'w') as outfile:
        json.dump(output_data, outfile, indent=4)

    print(f"Top {top_n} YouTubers saved to {output_file_path}")

# TODO: Creators not meeting language criteria are marked in console as excluded, but
# only skipped for writing TitleAnalysis data
def filter_videos(filepath, language):
    """
    Filter out videos that do not match the specified language and add relevant tags to videos that do.
    The function continues processing from where it left off based on the presence of the 'TitleAnalysis' flag.
    
    :param filepath: Path to the JSON file to read and save channels.
    :param language: Language to filter videos by.
    """
    try:
        # Load JSON data from file
        with open(filepath, 'r', encoding='utf-8') as file:
            channel_list = json.load(file)
    except Exception as e:
        print(f"Failed to load JSON data from {filepath}: {e}")
        return

    # Create a new list to store filtered channels
    filtered_channels = []

    for idx, channel in enumerate(channel_list, start=1):
        # Skip channels for which 'TitleAnalysis' is already present
        if "TitleAnalysis" in channel:
            print(f"Skipping already processed channel '{channel.get('Name', 'Unnamed')}'.")
            filtered_channels.append(channel)
            continue

        videos = channel.get("Videos", [])
        if not videos:
            print(f"Skipping channel '{channel.get('Name', 'Unnamed')}' with no videos.")
            continue

        titles = [video.get("title", "") for video in videos]

        try:
            # Artificial delay to mimic processing time
            time.sleep(0.4)

            # Analyze titles (assuming this function exists and performs the necessary analysis)
            analysis = analyze_titles(channel["Name"], titles, language)
            print(f"For: {channel['Name']}")
            print(analysis)

            # Check if the channel conforms to the language criteria
            if titles and analysis.conformsToLanguageCriteria:
                channel["TitleAnalysis"] = analysis.model_dump(mode="json")
                filtered_channels.append(channel)
                print(f"Channel '{channel['Name']}' added to filtered list.")
            else:
                print(f"Channel '{channel['Name']}' does not meet language criteria and is excluded.")

            # Save progress incrementally using a temporary file
            temp_filename = f"{filepath}.tmp"
            with open(temp_filename, 'w', encoding='utf-8') as temp_file:
                json.dump(channel_list, temp_file, indent=2, ensure_ascii=False)
            os.replace(temp_filename, filepath)
            print(f"Progress saved after processing channel {idx}: '{channel['Name']}'.")

        except Exception as e:
            print(f"Could not process data for channel: {channel.get('Name', 'Unknown Name')}")
            print(f"Error: {e}")
            continue

def main() -> None:
    """Re-rank a scraped channel list. Run explicitly, never on import."""
    yt_data = "yt_fr.json"

    weights = {
        # 0.8
        "metrics": {
            "AvgEngagementRate": {"weight": 0.3, "reverse": True},
            "AvgViewsPerSub": {"weight": 0.3, "reverse": True},
            "Subscribers": {"weight": 0.2, "reverse": True}
        },
        "title_analysis": {
            # 0.2
            "sensitivityRating": {"weight": 0.04, "reverse": False},  # Higher value: High sensivity ranked low
            "targetAgeInterest": {"weight": 0, "reverse": True},
            "likelyMusic": {"weight": 0.08, "reverse": False},
            "intellectuality": {"weight": 0.08, "reverse": True}
        }
    }

    weighted_rankings(
        yt_data, weights, top_n=750, output_file_path=str(data_file('yt_fr2.json'))
    )


if __name__ == "__main__":
    main()
