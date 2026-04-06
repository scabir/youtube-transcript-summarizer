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

def extract_text_from_yt_field(value):
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""

    simple_text = value.get("simpleText")
    if isinstance(simple_text, str):
        return simple_text.strip()

    runs = value.get("runs")
    if isinstance(runs, list):
        parts = []
        for run in runs:
            if isinstance(run, dict) and isinstance(run.get("text"), str):
                parts.append(run["text"])
        return "".join(parts).strip()

    return ""

def collect_marker_renderers(data):
    renderers = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"macroMarkersListItemRenderer", "chapterRenderer"} and isinstance(value, dict):
                    renderers.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return renderers

def extract_start_seconds_from_renderer(renderer):
    candidates_in_seconds = [
        renderer.get("onTap", {}).get("watchEndpoint", {}).get("startTimeSeconds"),
        renderer.get("navigationEndpoint", {}).get("watchEndpoint", {}).get("startTimeSeconds"),
    ]
    for candidate in candidates_in_seconds:
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue

    candidates_in_millis = [
        renderer.get("timeRangeStartMillis"),
        renderer.get("startTimeMs"),
        renderer.get("startTimeMillis"),
        renderer.get("startMillis"),
    ]
    for candidate in candidates_in_millis:
        if candidate is None:
            continue
        try:
            return float(candidate) / 1000.0
        except (TypeError, ValueError):
            continue

    time_description = extract_text_from_yt_field(renderer.get("timeDescription"))
    if time_description:
        try:
            return parse_timecode_to_seconds(time_description, "marker timestamp")
        except ValueError:
            return None

    return None

def extract_title_from_marker_renderer(renderer):
    title_candidates = [
        renderer.get("title"),
        renderer.get("chapterTitle"),
        renderer.get("headline"),
        renderer.get("headerText"),
    ]
    for candidate in title_candidates:
        title = extract_text_from_yt_field(candidate)
        if title:
            return title
    return ""

def extract_video_markers(yt):
    if yt is None:
        return []

    try:
        initial_data = yt.initial_data
    except Exception as e:
        print(f"Warning: Could not read video marker metadata: {e}")
        return []

    renderers = collect_marker_renderers(initial_data)
    if not renderers:
        return []

    markers = []
    for renderer in renderers:
        start_seconds = extract_start_seconds_from_renderer(renderer)
        if start_seconds is None:
            continue

        marker_title = extract_title_from_marker_renderer(renderer)
        markers.append(
            {
                "title": marker_title,
                "start_seconds": max(0.0, float(start_seconds)),
            }
        )

    if not markers:
        return []

    markers.sort(key=lambda marker: marker["start_seconds"])

    deduped = []
    seen_starts = set()
    for marker in markers:
        key = round(marker["start_seconds"], 3)
        if key in seen_starts:
            continue
        seen_starts.add(key)
        deduped.append(marker)

    return deduped

def normalize_marker_title(raw_title, index):
    title = (raw_title or "").strip()
    if not title:
        return f"Part {index}"

    if title.lower() in {"time marker", "time markers", "marker", "chapter"}:
        return f"Part {index}"

    return title

def build_marker_segments(markers, effective_start_seconds, effective_end_seconds, transcript_end_seconds):
    segments = []
    if not markers:
        return segments

    for index, marker in enumerate(markers):
        marker_start = float(marker["start_seconds"])
        if index + 1 < len(markers):
            marker_end = float(markers[index + 1]["start_seconds"])
        else:
            marker_end = transcript_end_seconds

        if marker_end <= marker_start:
            continue

        segment_start = max(marker_start, effective_start_seconds)
        segment_end = min(marker_end, effective_end_seconds)
        if segment_start >= segment_end:
            continue

        segments.append(
            {
                "index": index + 1,
                "title": normalize_marker_title(marker.get("title", ""), index + 1),
                "start_seconds": segment_start,
                "end_seconds": segment_end,
            }
        )

    return segments

def generate_summary_for_entries(transcript_entries, output_language, quality_mode):
    full_content, usage_report = generate_summary(
        transcript_entries,
        output_language,
        quality_mode=quality_mode,
    )
    if not full_content:
        return None

    print_usage_report(usage_report)
    return full_content

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
        '--split-by-markers',
        action='store_true',
        help='If available, split by video markers/chapters and generate one summary file per segment.',
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

    yt = None
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

    if args.split_by_markers:
        markers = extract_video_markers(yt)
        segments = build_marker_segments(
            markers,
            effective_start_seconds,
            effective_end_seconds,
            transcript_end_seconds,
        )
        if segments:
            successful_segments = 0
            print(f"Found {len(segments)} marker segments in selected range.")
            for segment in segments:
                segment_entries = filter_transcript_entries_by_time_range(
                    transcript_entries,
                    segment["start_seconds"],
                    segment["end_seconds"],
                )
                if not segment_entries:
                    continue

                segment_start_tc = seconds_to_timecode(segment["start_seconds"])
                segment_end_tc = seconds_to_timecode(segment["end_seconds"])
                segment_label = segment["title"]
                segment_index_prefix = f"{segment['index']:02d}"
                print(
                    f"Summarizing segment {segment['index']}/{len(segments)}: "
                    f"{segment_label} ({segment_start_tc} - {segment_end_tc})"
                )

                full_content = generate_summary_for_entries(
                    segment_entries,
                    args.output,
                    args.quality,
                )
                if not full_content:
                    print(f"Warning: Failed to summarize segment '{segment_label}'.")
                    continue

                segment_title = (
                    f"{video_id}_{segment_index_prefix}_{segment_label} "
                    f"[{segment_start_tc}-{segment_end_tc}]"
                )
                save_markdown(full_content, segment_title, video_id)
                successful_segments += 1

            if successful_segments == 0:
                print("Error: Could not generate summaries for any marker segment.")
            return

        print("No video markers found. Falling back to single summary for selected range.")

    full_content = generate_summary_for_entries(
        selected_entries,
        args.output,
        args.quality,
    )
    if not full_content:
        print("Error: Could not generate summary")
        return

    if start_seconds is not None or end_seconds is not None:
        range_suffix = (
            f"{seconds_to_timecode(effective_start_seconds)}-"
            f"{seconds_to_timecode(effective_end_seconds)}"
        )
        video_title = f"{video_title} [{range_suffix}]"

    save_markdown(full_content, video_title, video_id)

if __name__ == "__main__":
    main()
