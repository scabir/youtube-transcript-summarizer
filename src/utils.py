import re
import os
from youtube_transcript_api import YouTubeTranscriptApi
from config_loader import load_config
import json
from pathlib import Path

config = load_config()
ytt_api = YouTubeTranscriptApi()

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

def build_language_priority(language):
    languages = []
    if language:
        languages.append(language)

        base_lang = language.split('-')[0]
        if base_lang != language:
            languages.append(base_lang)

    if 'en' not in languages:
        languages.append('en')

    return languages

def fetch_transcript(video_id, language='en'):
    languages = build_language_priority(language)
    print(f"Attempting transcript fetch with language priority: {languages}")

    try:
        fetched_transcript = ytt_api.fetch(video_id, languages=languages)
        print(
            "Successfully retrieved transcript in language: "
            f"{fetched_transcript.language_code}"
        )
        return fetched_transcript.to_raw_data()
    except Exception as e:
        print(f"Error retrieving transcript for {video_id}: {str(e)}")
        return None

def get_transcript(video_id, language='en'):
    print(f"Attempting to retrieve transcript for video ID: {video_id}")
    print(f"Language: {language}")
    
    cached_transcript = load_transcript_from_cache(video_id, language)
    if cached_transcript:
        print(f"Loaded transcript from cache for video ID: {video_id}")
        return normalize_transcript_entries(cached_transcript)
    
    transcript = fetch_transcript(video_id, language)
    
    if not transcript:
        return None
    
    cache_file = save_transcript_to_cache(video_id, transcript, language)
    print(f"Saved transcript to cache: {cache_file}")
    
    return normalize_transcript_entries(transcript)

def normalize_transcript_entries(transcript):
    if transcript is None:
        return None

    if not isinstance(transcript, list):
        raise ValueError("Transcript must be a list")

    normalized = []
    for entry in transcript:
        if not isinstance(entry, dict):
            raise ValueError("Transcript entries must be dictionaries")
        if 'text' not in entry:
            raise ValueError("Transcript entry missing required 'text' field")
        if not isinstance(entry['text'], str):
            raise ValueError("Transcript text field must be a string")

        start = entry.get('start', 0)
        duration = entry.get('duration', 0)
        try:
            start = float(start)
        except (TypeError, ValueError):
            start = 0.0
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 0.0

        normalized.append(
            {
                'text': entry['text'].strip(),
                'start': max(0.0, start),
                'duration': max(0.0, duration),
            }
        )

    return [entry for entry in normalized if entry['text']]

def reduce_transcript(transcript):
    normalized = normalize_transcript_entries(transcript)
    if normalized is None:
        return None

    return "\n".join(entry['text'] for entry in normalized)

def save_markdown(content, video_title, video_id):
    filename = generate_filename(video_title, video_id)
    
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w') as f:
        f.write(content)
    print(f"Summary saved to {filename}")
