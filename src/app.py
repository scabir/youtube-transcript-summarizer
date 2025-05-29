import argparse
from pytube import YouTube
from utils import extract_video_id, get_transcript, save_markdown
from generator import generate_structure, generate_detailed_content
from config_loader import load_config

config = load_config()

def main():
    parser = argparse.ArgumentParser(description="YouTube Transcript Summarizer")
    parser.add_argument("--url", required=True, help="YouTube video URL")
    parser.add_argument('--language', type=str, default=config['language']['default'], help='Language code for the transcript.')
    parser.add_argument('--output', type=str, default='en', help='Output language code (default: en)')
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    if not video_id:
        print("Error: Invalid YouTube URL")
        return

    try:
        yt = YouTube(args.url)
        video_title = yt.title
    except Exception:
        video_title = video_id

    transcript = get_transcript(video_id, args.language)
    if not transcript:
        print("Error: Could not retrieve transcript")
        return

    structure = generate_structure(transcript, args.output)
    if not structure:
        print("Error: Could not generate structure")
        return

    full_content = generate_detailed_content(transcript, structure, args.output)
    if not full_content:
        print("Error: Could not generate detailed content")
        return

    save_markdown(full_content, video_title, video_id)

if __name__ == "__main__":
    main()
