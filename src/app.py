import argparse
from pytube import YouTube
from utils import extract_video_id, get_transcript, save_markdown
from generator import (
    DEFAULT_QUALITY,
    QUALITY_MODES,
    generate_summary,
    print_usage_report,
)
from config_loader import load_config

config = load_config()
configured_quality = config.get('summarization', {}).get('default_quality', DEFAULT_QUALITY)
if configured_quality not in QUALITY_MODES:
    configured_quality = DEFAULT_QUALITY

def main():
    parser = argparse.ArgumentParser(description="YouTube Transcript Summarizer")
    parser.add_argument("--url", required=True, help="YouTube video URL")
    parser.add_argument('--language', type=str, default=config['language']['default'], help='Language code for the transcript.')
    parser.add_argument('--output', type=str, default='en', help='Output language code (default: en)')
    parser.add_argument(
        '--quality',
        type=str,
        choices=QUALITY_MODES,
        default=configured_quality,
        help='Summary quality/cost mode: economy, balanced, or max_quality.',
    )
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

    transcript_entries = get_transcript(video_id, args.language)
    if not transcript_entries:
        print("Error: Could not retrieve transcript")
        return

    full_content, usage_report = generate_summary(
        transcript_entries,
        args.output,
        quality_mode=args.quality,
    )
    if not full_content:
        print("Error: Could not generate summary")
        return

    print_usage_report(usage_report)
    save_markdown(full_content, video_title, video_id)

if __name__ == "__main__":
    main()
