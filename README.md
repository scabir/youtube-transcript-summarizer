# YouTube Transcript Summarizer

Generate high-quality, token-efficient summaries from YouTube transcripts using OpenAI models.

## How It Works

The summarization pipeline is adaptive:

1. Fetch transcript (with local cache in `results/_cache`).
2. Estimate transcript size and pick a route:
   - `short`: single-pass summary with an explicit plan section.
   - `medium` / `long`: chunk transcript -> extract chunk notes -> generate plan -> synthesize final summary.
3. Scale output length dynamically so long transcripts get sufficiently detailed summaries, while short transcripts stay concise.
4. Print per-call token usage and estimated cost telemetry.

## Configuration

Create `config/config.yaml` from `config/__config_template.yaml`.

```yaml
openai:
  api_key: "YOUR_OPENAI_API_KEY"
  default_model: "gpt-5.4"
  max_tokens: 128000

paths:
  results_folder: "results"

language:
  default: "en"
  supported: ["en", "tr", "es", "fr", "de"]

summarization:
  default_quality: "balanced" # economy | balanced | max_quality
  short_threshold_tokens: 2200
  long_threshold_tokens: 12000
  chunk_target_tokens: 1800
  max_chunks: 18
  map_max_tokens: 900
  plan_max_tokens: 1800
  map_reasoning_effort: "low"
  plan_reasoning_effort: "low"
  short_reasoning_effort: "low"
  final_reasoning_effort: "medium"
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
```

## Usage

From repository root:

```bash
.venv/bin/python src/app.py --url "https://www.youtube.com/watch?v=0z9_MhcYvcY"
```

Optional arguments:

- `--language`: transcript language (default comes from config).
- `--output`: output language for summary (default `en`).
- `--quality`: `economy`, `balanced`, or `max_quality`.
- `--start`: optional start time (`mm:ss` or `hh:mm:ss`).
- `--end`: optional end time (`mm:ss` or `hh:mm:ss`).
- `--split-by-markers`: if the video has markers/chapters, generate one summary file per marker segment.

Example:

```bash
.venv/bin/python src/app.py \
  --url "https://www.youtube.com/watch?v=0z9_MhcYvcY" \
  --language tr \
  --output en \
  --quality balanced
```

Summarize only a specific segment:

```bash
.venv/bin/python src/app.py \
  --url "https://www.youtube.com/watch?v=0z9_MhcYvcY" \
  --start 12:32 \
  --end 14:05
```

Hour format is also supported:

```bash
.venv/bin/python src/app.py \
  --url "https://www.youtube.com/watch?v=0z9_MhcYvcY" \
  --start 01:12:14 \
  --end 12:03:04
```

Split by YouTube markers/chapters:

```bash
.venv/bin/python src/app.py \
  --url "https://www.youtube.com/watch?v=0z9_MhcYvcY" \
  --split-by-markers
```

Marker names are used in output filenames. If a marker title is generic (for example `Time Marker`), a fallback part label is used.
Split files are prefixed with YouTube ID and zero-padded part numbers (`<video_id>_01_`, `<video_id>_02_`, ...).

Important for `zsh`: always quote URL values (`"..."`) so `?` and `&` are not interpreted by the shell.

## Output

- Final summary is saved as markdown in `results/`.
- Transcript cache is saved in `results/_cache/`.
- Runtime logs include:
  - chosen summarization route,
  - selected models by stage,
  - per-call token usage,
  - aggregated usage/cost estimate.

By default, summaries are generated as fluent prose without inline timestamp markers.

## License

MIT License
