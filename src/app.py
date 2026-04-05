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

def parse_timecode_to_seconds(value, argument_name):
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None

    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        if not (minutes.isdigit() and seconds.isdigit()):
            raise ValueError(f"{argument_name} must be in mm:ss or hh:mm:ss format.")
        minutes_int = int(minutes)
        seconds_int = int(seconds)
        if seconds_int >= 60:
            raise ValueError(f"{argument_name} seconds must be between 00 and 59.")
        return float(minutes_int * 60 + seconds_int)

    if len(parts) == 3:
        hours, minutes, seconds = parts
        if not (hours.isdigit() and minutes.isdigit() and seconds.isdigit()):
            raise ValueError(f"{argument_name} must be in mm:ss or hh:mm:ss format.")
        hours_int = int(hours)
        minutes_int = int(minutes)
        seconds_int = int(seconds)
        if minutes_int >= 60 or seconds_int >= 60:
            raise ValueError(f"{argument_name} minutes/seconds must be between 00 and 59 for hh:mm:ss.")
        return float(hours_int * 3600 + minutes_int * 60 + seconds_int)

    raise ValueError(f"{argument_name} must be in mm:ss or hh:mm:ss format.")

def seconds_to_timecode(total_seconds):
    total_seconds_int = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds_int, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

def get_transcript_end_seconds(transcript_entries):
    if not transcript_entries:
        return 0.0
    last_entry = transcript_entries[-1]
    return float(last_entry.get("start", 0)) + float(last_entry.get("duration", 0))

def filter_transcript_entries_by_time_range(transcript_entries, start_seconds, end_seconds):
    filtered_entries = []
    for entry in transcript_entries:
        entry_start = float(entry.get("start", 0))
        entry_end = entry_start + float(entry.get("duration", 0))

        if entry_end < start_seconds:
            continue
        if entry_start > end_seconds:
            continue

        filtered_entries.append(entry)

    return filtered_entries

def main():
    parser = argparse.ArgumentParser(description="YouTube Transcript Summarizer")
    parser.add_argument("--url", required=True, help="YouTube video URL")
    parser.add_argument('--language', type=str, default=config['language']['default'], help='Language code for the transcript.')
    parser.add_argument('--output', type=str, default='en', help='Output language code (default: en)')
    parser.add_argument(
        '--start',
        type=str,
        default=None,
        help='Optional start time (mm:ss or hh:mm:ss). Defaults to beginning.',
    )
    parser.add_argument(
        '--end',
        type=str,
        default=None,
        help='Optional end time (mm:ss or hh:mm:ss). Defaults to transcript end.',
    )
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

    try:
        start_seconds = parse_timecode_to_seconds(args.start, "--start")
        end_seconds = parse_timecode_to_seconds(args.end, "--end")
    except ValueError as e:
        print(f"Error: {e}")
        return

    if start_seconds is not None and end_seconds is not None and start_seconds > end_seconds:
        print("Error: --start cannot be greater than --end.")
        return

    transcript_end_seconds = get_transcript_end_seconds(transcript_entries)
    effective_start_seconds = 0.0 if start_seconds is None else start_seconds
    effective_end_seconds = transcript_end_seconds if end_seconds is None else end_seconds
    if effective_end_seconds > transcript_end_seconds:
        effective_end_seconds = transcript_end_seconds
    if effective_start_seconds < 0:
        effective_start_seconds = 0.0

    if effective_start_seconds > effective_end_seconds:
        print("Error: The selected time range is invalid after normalization.")
        return

    selected_entries = filter_transcript_entries_by_time_range(
        transcript_entries,
        effective_start_seconds,
        effective_end_seconds,
    )
    if not selected_entries:
        print(
            "Error: No transcript entries found in selected range "
            f"({seconds_to_timecode(effective_start_seconds)} - {seconds_to_timecode(effective_end_seconds)})."
        )
        return

    print(
        "Using transcript range: "
        f"{seconds_to_timecode(effective_start_seconds)} - {seconds_to_timecode(effective_end_seconds)}"
    )

    full_content, usage_report = generate_summary(
        selected_entries,
        args.output,
        quality_mode=args.quality,
    )
    if not full_content:
        print("Error: Could not generate summary")
        return

    print_usage_report(usage_report)
    if start_seconds is not None or end_seconds is not None:
        range_suffix = (
            f"{seconds_to_timecode(effective_start_seconds)}-"
            f"{seconds_to_timecode(effective_end_seconds)}"
        )
        video_title = f"{video_title} [{range_suffix}]"

    save_markdown(full_content, video_title, video_id)

if __name__ == "__main__":
    main()
