import re
import os
from youtube_transcript_api import YouTubeTranscriptApi
from config_loader import load_config
import json
from pathlib import Path

config = load_config()

def generate_filename(video_title, video_id):
    if video_title == video_id:
        return os.path.join(config['paths']['results_folder'], f"{video_id}.md")
    
    clean_title = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in video_title)
    clean_title = clean_title.strip().replace(' ', '_')
    
    filename = f"{clean_title}__{video_id}.md"
    return os.path.join(config['paths']['results_folder'], filename)

def extract_video_id(url):
    youtube_regex = (
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|\.+\?v=)?([^&=%\?]{11})'
    )
    match = re.match(youtube_regex, url)
    return match.group(6) if match else None

def get_cache_path():
    cache_dir = Path(config['paths']['results_folder']) / '_cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

def save_transcript_to_cache(video_id, transcript, language='en'):
    cache_dir = get_cache_path()
    cache_file = cache_dir / f"{video_id}_{language}.json"
    
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
    return str(cache_file)

def load_transcript_from_cache(video_id, language='en'):
    cache_dir = get_cache_path()
    cache_file = cache_dir / f"{video_id}_{language}.json"
    
    if not cache_file.exists():
        return None
    
    with open(cache_file, 'r', encoding='utf-8') as f:
        transcript = json.load(f)
    return transcript

def get_fallback_transcript(video_id, base_lang):
    try:
        print(f"Attempting to retrieve transcript with base language: {base_lang}")
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[base_lang])
        print(f"Successfully retrieved transcript in base language: {base_lang}")
        return transcript
    except Exception as e:
        print(f"Error retrieving transcript with base language {base_lang}: {str(e)}")
        
    try:
        print("Attempting to retrieve transcript in English as fallback")
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        print("Successfully retrieved transcript in English")
        return transcript
    except Exception as e:
        print(f"Error retrieving transcript in English: {str(e)}")
        print("No transcript available in any language")
        return None

def fetch_transcript(video_id, language='en'):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
        print(f"Successfully retrieved transcript in language: {language}")
        return transcript
    except Exception as e:
        print(f"Error retrieving transcript with language {language}: {str(e)}")
        
        base_lang = language.split('-')[0]
        if base_lang != language:
            return get_fallback_transcript(video_id, base_lang)
        return None

def get_transcript(video_id, language='en'):
    print(f"Attempting to retrieve transcript for video ID: {video_id}")
    print(f"Language: {language}")
    
    cached_transcript = load_transcript_from_cache(video_id, language)
    if cached_transcript:
        print(f"Loaded transcript from cache for video ID: {video_id}")
        clean_transcript = reduce_transcript(cached_transcript)
        return clean_transcript
    
    transcript = fetch_transcript(video_id, language)
    
    if not transcript:
        return None
    
    cache_file = save_transcript_to_cache(video_id, transcript, language)
    print(f"Saved transcript to cache: {cache_file}")
    
    clean_transcript = reduce_transcript(transcript)
    return clean_transcript

def reduce_transcript(transcript):
    if transcript is None:
        return None
    
    if not isinstance(transcript, list):
        raise ValueError("Transcript must be a list")
    
    for entry in transcript:
        if not isinstance(entry, dict):
            raise ValueError("Transcript entries must be dictionaries")
        if 'text' not in entry:
            raise ValueError("Transcript entry missing required 'text' field")
        if not isinstance(entry['text'], str):
            raise ValueError("Transcript text field must be a string")
    
    return "\n".join(entry['text'] for entry in transcript)

def save_markdown(content, video_title, video_id):
    filename = generate_filename(video_title, video_id)
    
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w') as f:
        f.write(content)
    print(f"Summary saved to {filename}")
