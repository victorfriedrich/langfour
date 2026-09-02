from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO

def create_thumbnail_collage(videos):
    # Calculate grid dimensions
    num_videos = len(videos)
    cols = 4
    rows = (num_videos + cols - 1) // cols
    
    # Define dimensions
    thumb_width = 290
    thumb_height = 160
    title_height = 60
    spacing = 20
    
    # Total dimensions for each cell (thumbnail + title)
    cell_height = thumb_height + title_height + spacing
    
    # Create blank canvas
    canvas_width = cols * (thumb_width + spacing) - spacing
    canvas_height = rows * cell_height - spacing
    canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')
    draw = ImageDraw.Draw(canvas)
    
    # Try to load a font, fall back to default if not available
    try:
        font = ImageFont.truetype("Arial.ttf", 15)
    except:
        font = ImageFont.load_default()

    for idx, video in enumerate(videos):
        try:
            # Get thumbnail
            thumbnail_url = f"https://img.youtube.com/vi/{video['id']}/mqdefault.jpg"
            response = requests.get(thumbnail_url)
            thumb = Image.open(BytesIO(response.content))
            
            # Resize thumbnail if needed
            thumb = thumb.resize((thumb_width, thumb_height))
            
            # Calculate position
            x = (idx % cols) * (thumb_width + spacing)
            y = (idx // cols) * cell_height
            
            # Paste thumbnail
            canvas.paste(thumb, (x, y))
            
            # Add title (wrapped if too long)
            title = video['title']
            # Wrap text at 40 characters
            wrapped_title = '\n'.join([title[i:i+40] for i in range(0, len(title), 40)])
            draw.text((x, y + thumb_height + 5), wrapped_title, font=font, fill='black')
            
        except Exception as e:
            print(f"Error processing video {video['id']}: {str(e)}")

    return canvas

# # Example channel data
# channel_data = {
#     "Name": "Kinder Spielzeug Kanal",
#     "Videos": [
#         {
#             "id": "lkdenSDtKxc",
#             "title": "The Kids play astronauts on a rocket ship 🚀👨‍🚀",
#         },
#         {
#             "id": "RgFkO3feEFg",
#             "title": "Let's meet firefighters! | Educational Videos for Kids | Kidibli",
#         },
#         {
#             "id": "VyS9aaIRYMA",
#             "title": "The Kids discover big vehicles 👷🚛",
#         },
#         {
#             "id": "7nAWi6qAhs4",
#             "title": "Let's learn about Space and Rockets! | Science Videos for Kids | Kidibli",
#         },
#         {
#             "id": "vG6zsgbfMRI",
#             "title": "Let's learn about Firetrucks! | Educational Videos for Kids | Kidibli",
#         },
#         {
#             "id": "faoodwcPqUc",
#             "title": "Call the Firefighters! | Fire Trucks Song for Kids | Kidibli",
#         },
#         {
#             "id": "5f2ABrD8Aeo",
#             "title": "Let's learn about Airplanes! | Educational Videos for Kids | Kidibli",
#         }
#     ]
# }

# # Create and save the collage
# collage = create_thumbnail_collage(channel_data["Videos"])
# collage.save(f"youtube_thumbnails/{channel_data['Name']}_collage.jpg")