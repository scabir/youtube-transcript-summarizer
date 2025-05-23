import re
import os
from youtube_transcript_api import YouTubeTranscriptApi

def extract_video_id(url):
    """Extract YouTube video ID from URL."""
    youtube_regex = (
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|\.+\?v=)?([^&=%\?]{11})'
    )
    match = re.match(youtube_regex, url)
    return match.group(6) if match else None

def get_transcript(video_id, language='en'):
    """Retrieve transcript for a YouTube video."""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
        clean_transcript = ' '.join([entry['text'] for entry in transcript])
        return clean_transcript
    except Exception:
        base_lang = language.split('-')[0]
        if base_lang != language:
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[base_lang])
                clean_transcript = ' '.join([entry['text'] for entry in transcript])
                return clean_transcript
            except Exception:
                pass
        
        return None

from generator import generate_filename

def save_markdown(content, video_title, video_id):
    """Save content to a markdown file in the results directory."""
    filename = generate_filename(video_title, video_id)
    
    with open(filename, 'w') as f:
        f.write(content)
    print(f"Summary saved to {filename}")
