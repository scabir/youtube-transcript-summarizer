import re
import os
from youtube_transcript_api import YouTubeTranscriptApi
from config_loader import load_config

config = load_config()

def generate_filename(video_title, video_id):
    """Generate a filename using video title and ID."""
    if video_title == video_id:
        return os.path.join(config['paths']['results_folder'], f"{video_id}.md")
    
    clean_title = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in video_title)
    clean_title = clean_title.strip().replace(' ', '_')
    
    filename = f"{clean_title}__{video_id}.md"
    return os.path.join(config['paths']['results_folder'], filename)

def extract_video_id(url):
    """Extract YouTube video ID from URL."""
    youtube_regex = (
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|\.+\?v=)?([^&=%\?]{11})'
    )
    match = re.match(youtube_regex, url)
    return match.group(6) if match else None

def get_transcript(video_id, language='en'):
    """Retrieve transcript for a YouTube video."""
    print(f"Attempting to retrieve transcript for video ID: {video_id}")
    print(f"Language: {language}")
    
    try:
        # First try with the exact language code
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
        print(f"Successfully retrieved transcript in language: {language}")
        clean_transcript = ' '.join([entry['text'] for entry in transcript])
        return clean_transcript
    except Exception as e:
        print(f"Error retrieving transcript with language {language}: {str(e)}")
        
        # Try with base language if it's different
        base_lang = language.split('-')[0]
        if base_lang != language:
            try:
                print(f"Attempting to retrieve transcript with base language: {base_lang}")
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[base_lang])
                print(f"Successfully retrieved transcript in base language: {base_lang}")
                clean_transcript = ' '.join([entry['text'] for entry in transcript])
                return clean_transcript
            except Exception as e:
                print(f"Error retrieving transcript with base language {base_lang}: {str(e)}")
                pass
        
        # Try with English as fallback
        try:
            print("Attempting to retrieve transcript in English as fallback")
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
            print("Successfully retrieved transcript in English")
            clean_transcript = ' '.join([entry['text'] for entry in transcript])
            return clean_transcript
        except Exception as e:
            print(f"Error retrieving transcript in English: {str(e)}")
            print("No transcript available in any language")
            return None

def save_markdown(content, video_title, video_id):
    """Save content to a markdown file in the results directory."""
    filename = generate_filename(video_title, video_id)
    
    # Create the results directory if it doesn't exist
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w') as f:
        f.write(content)
    print(f"Summary saved to {filename}")
