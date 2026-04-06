import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import openai

from config_loader import load_config

config = load_config()

OPENAI_CONFIG = config["openai"]
DEFAULT_MODEL = OPENAI_CONFIG["default_model"]
MAX_TOKENS = OPENAI_CONFIG["max_tokens"]

SUMMARIZATION_CONFIG = config.get("summarization", {})

DEFAULT_QUALITY = SUMMARIZATION_CONFIG.get("default_quality", "balanced")
QUALITY_MODES = ("economy", "balanced", "max_quality")

SHORT_THRESHOLD_TOKENS = int(SUMMARIZATION_CONFIG.get("short_threshold_tokens", 2200))
LONG_THRESHOLD_TOKENS = int(SUMMARIZATION_CONFIG.get("long_threshold_tokens", 12000))
CHUNK_TARGET_TOKENS = int(SUMMARIZATION_CONFIG.get("chunk_target_tokens", 1800))
MAX_CHUNKS = int(SUMMARIZATION_CONFIG.get("max_chunks", 18))
MAP_MAX_TOKENS = int(SUMMARIZATION_CONFIG.get("map_max_tokens", 900))
PLAN_MAX_TOKENS = int(SUMMARIZATION_CONFIG.get("plan_max_tokens", 1800))
MAP_REASONING_EFFORT = str(SUMMARIZATION_CONFIG.get("map_reasoning_effort", "low"))
PLAN_REASONING_EFFORT = str(SUMMARIZATION_CONFIG.get("plan_reasoning_effort", "low"))
SHORT_REASONING_EFFORT = str(SUMMARIZATION_CONFIG.get("short_reasoning_effort", "low"))
FINAL_REASONING_EFFORT = str(SUMMARIZATION_CONFIG.get("final_reasoning_effort", "medium"))

MODEL_PRICING_PER_MILLION = {
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 3.00},
    "gpt-5.4-nano": {"input": 0.15, "output": 0.60},
}

DEFAULT_QUALITY_MODELS = {
    "economy": {
        "worker": "gpt-5.4-nano",
        "planner": "gpt-5.4-nano",
        "writer": "gpt-5.4-mini",
    },
    "balanced": {
        "worker": "gpt-5.4-mini",
        "planner": "gpt-5.4-mini",
        "writer": "gpt-5.4-mini",
    },
    "max_quality": {
        "worker": "gpt-5.4-mini",
        "planner": "gpt-5.4",
        "writer": "gpt-5.4",
    },
}

client = openai.OpenAI(api_key=OPENAI_CONFIG["api_key"])


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def estimate_tokens(text: str) -> int:
    # Quick approximation keeps the pipeline dependency-free and cheap.
    return max(1, len(text) // 4)


def format_timestamp(seconds: float) -> str:
    seconds_int = max(0, int(seconds))
    hours, remainder = divmod(seconds_int, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def normalize_transcript_entries(transcript_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for entry in transcript_entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            continue

        try:
            start = float(entry.get("start", 0))
        except (TypeError, ValueError):
            start = 0.0
        try:
            duration = float(entry.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0.0

        normalized.append(
            {
                "text": text,
                "start": max(0.0, start),
                "duration": max(0.0, duration),
            }
        )
    return normalized


def transcript_duration_minutes(transcript_entries: List[Dict[str, Any]]) -> float:
    if not transcript_entries:
        return 0.0
    last = transcript_entries[-1]
    end_second = float(last.get("start", 0)) + float(last.get("duration", 0))
    return max(0.0, end_second / 60.0)


def transcript_token_estimate(transcript_entries: List[Dict[str, Any]]) -> int:
    return sum(estimate_tokens(entry["text"]) for entry in transcript_entries)


def choose_route(transcript_tokens: int) -> str:
    if transcript_tokens <= SHORT_THRESHOLD_TOKENS:
        return "short"
    if transcript_tokens <= LONG_THRESHOLD_TOKENS:
        return "medium"
    return "long"


def choose_models(quality_mode: str) -> Dict[str, str]:
    quality_mode = quality_mode if quality_mode in QUALITY_MODES else DEFAULT_QUALITY
    base_models = dict(DEFAULT_QUALITY_MODELS[quality_mode])

    overrides = SUMMARIZATION_CONFIG.get("quality_models", {}).get(quality_mode, {})
    if isinstance(overrides, dict):
        for key in ("worker", "planner", "writer"):
            override_value = overrides.get(key)
            if override_value:
                base_models[key] = override_value

    return base_models


def choose_target_output_tokens(transcript_tokens: int, duration_minutes: float, route: str) -> int:
    if route == "short":
        base_tokens = int(transcript_tokens * 0.22)
        min_tokens = 350
        max_tokens = min(MAX_TOKENS, 1800)
        duration_floor = int(duration_minutes * 35)
    elif route == "medium":
        base_tokens = int(transcript_tokens * 0.16)
        min_tokens = 1200
        max_tokens = min(MAX_TOKENS, 7000)
        duration_floor = int(duration_minutes * 50)
    else:
        base_tokens = int(transcript_tokens * 0.14)
        min_tokens = 3000
        max_tokens = min(MAX_TOKENS, 20000)
        duration_floor = int(duration_minutes * 70)

    if max_tokens < min_tokens:
        min_tokens = max_tokens

    target = max(base_tokens, duration_floor)
    return clamp(target, min_tokens, max_tokens)


def choose_chunk_target_tokens(route: str) -> int:
    if route == "medium":
        return CHUNK_TARGET_TOKENS
    if route == "long":
        return max(1200, CHUNK_TARGET_TOKENS - 400)
    return CHUNK_TARGET_TOKENS


def chunk_transcript(
    transcript_entries: List[Dict[str, Any]],
    target_tokens: int,
    max_chunks: int,
) -> List[List[Dict[str, Any]]]:
    chunks: List[List[Dict[str, Any]]] = []
    current_chunk: List[Dict[str, Any]] = []
    current_tokens = 0

    for entry in transcript_entries:
        entry_tokens = estimate_tokens(entry["text"])

        if current_chunk and current_tokens + entry_tokens > target_tokens:
            chunks.append(current_chunk)
            current_chunk = []
            current_tokens = 0

        current_chunk.append(entry)
        current_tokens += entry_tokens

    if current_chunk:
        chunks.append(current_chunk)

    if len(chunks) <= max_chunks:
        return chunks

    # Collapse chunks when transcripts are extremely long to keep API call count bounded.
    merged_chunks: List[List[Dict[str, Any]]] = []
    group_size = int(math.ceil(len(chunks) / max_chunks))
    for index in range(0, len(chunks), group_size):
        merged: List[Dict[str, Any]] = []
        for chunk in chunks[index : index + group_size]:
            merged.extend(chunk)
        merged_chunks.append(merged)

    return merged_chunks


def chunk_to_prompt_text(chunk_entries: List[Dict[str, Any]]) -> str:
    lines = []
    for entry in chunk_entries:
        ts = format_timestamp(float(entry["start"]))
        lines.append(f"[{ts}] {entry['text']}")
    return "\n".join(lines)


def transcript_entries_to_plain_text(transcript_entries: List[Dict[str, Any]]) -> str:
    return "\n".join(entry["text"] for entry in transcript_entries if entry.get("text"))


def extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, flags=re.DOTALL)
    if fenced_match:
        candidate = fenced_match.group(1).strip()
    else:
        start_idx = raw_text.find("{")
        end_idx = raw_text.rfind("}")
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return None
        candidate = raw_text[start_idx : end_idx + 1].strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict):
        return parsed
    return None


def model_for_pricing(model_name: str) -> Optional[str]:
    if model_name.startswith("gpt-5.4-mini"):
        return "gpt-5.4-mini"
    if model_name.startswith("gpt-5.4-nano"):
        return "gpt-5.4-nano"
    if model_name.startswith("gpt-5.4"):
        return "gpt-5.4"
    return None


def estimate_cost_usd(model_name: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    price_key = model_for_pricing(model_name)
    if not price_key:
        return None

    pricing = MODEL_PRICING_PER_MILLION.get(price_key)
    if not pricing:
        return None

    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def init_usage_report(
    quality_mode: str,
    route: str,
    transcript_tokens: int,
    target_output_tokens: int,
) -> Dict[str, Any]:
    return {
        "quality_mode": quality_mode,
        "route": route,
        "transcript_tokens_estimate": transcript_tokens,
        "target_output_tokens": target_output_tokens,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "steps": [],
    }


def track_usage(
    usage_report: Dict[str, Any],
    step_name: str,
    model_name: str,
    usage: Any,
) -> None:
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)

    usage_report["calls"] += 1
    usage_report["prompt_tokens"] += prompt_tokens
    usage_report["completion_tokens"] += completion_tokens
    usage_report["total_tokens"] += total_tokens

    step_cost = estimate_cost_usd(model_name, prompt_tokens, completion_tokens)
    if step_cost is not None:
        usage_report["estimated_cost_usd"] += step_cost

    usage_report["steps"].append(
        {
            "step": step_name,
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": step_cost,
        }
    )

    cost_note = f", est_cost=${step_cost:.4f}" if step_cost is not None else ""
    print(
        f"[AI] step={step_name} model={model_name} "
        f"prompt={prompt_tokens} completion={completion_tokens} total={total_tokens}{cost_note}"
    )


def content_to_text(content: Union[str, List[Any], None]) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    text_parts: List[str] = []
    for item in content:
        if isinstance(item, dict):
            # Some models return {"type":"text"}, others use {"type":"output_text"}.
            text_value = item.get("text")
            if isinstance(text_value, str):
                text_parts.append(text_value)
            nested_text = item.get("output_text")
            if isinstance(nested_text, str):
                text_parts.append(nested_text)
        else:
            text_value = getattr(item, "text", None)
            if isinstance(text_value, str):
                text_parts.append(text_value)
            # Defensive fallback for SDK objects where text may be nested.
            output_text = getattr(item, "output_text", None)
            if isinstance(output_text, str):
                text_parts.append(output_text)

    return "\n".join(part.strip() for part in text_parts if part and part.strip()).strip()


def call_chat_completion(
    step_name: str,
    model_name: str,
    messages: List[Dict[str, str]],
    max_completion_tokens: int,
    usage_report: Dict[str, Any],
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    reasoning_effort: Optional[str] = None,
    response_format: Optional[Dict[str, str]] = None,
    retry_on_empty_output: bool = True,
) -> Optional[str]:
    request_args: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }
    if temperature is not None:
        request_args["temperature"] = temperature
    if top_p is not None:
        request_args["top_p"] = top_p
    if frequency_penalty is not None:
        request_args["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        request_args["presence_penalty"] = presence_penalty

    if reasoning_effort:
        request_args["reasoning_effort"] = reasoning_effort
    if response_format:
        request_args["response_format"] = response_format

    response = None
    try:
        response = client.chat.completions.create(**request_args)
    except openai.RateLimitError as exc:
        error_text = str(exc)
        if "insufficient_quota" in error_text:
            print(
                "OpenAI quota exceeded (insufficient_quota). "
                "Use --quality economy/balanced or add billing credits."
            )
        print(f"Error during {step_name}: {error_text}")
        return None
    except Exception as exc:
        print(f"Error during {step_name}: {exc}")
        return None

    track_usage(usage_report, step_name, model_name, response.usage)
    choice = response.choices[0]
    text_output = content_to_text(choice.message.content)
    if text_output:
        return text_output

    finish_reason = getattr(choice, "finish_reason", "unknown")
    print(
        f"[AI] step={step_name} returned empty content "
        f"(finish_reason={finish_reason}, max_completion_tokens={max_completion_tokens})"
    )

    if retry_on_empty_output and finish_reason == "length":
        retry_max_tokens = min(
            MAX_TOKENS,
            max(max_completion_tokens + 400, int(max_completion_tokens * 2.2), 1800),
        )
        if retry_max_tokens > max_completion_tokens:
            print(
                f"[AI] step={step_name} retrying with larger output budget "
                f"({max_completion_tokens} -> {retry_max_tokens})"
            )
            return call_chat_completion(
                step_name=step_name,
                model_name=model_name,
                messages=messages,
                max_completion_tokens=retry_max_tokens,
                usage_report=usage_report,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                reasoning_effort="low",
                response_format=response_format,
                retry_on_empty_output=False,
            )

    return None


def build_fallback_chunk_note(
    chunk_entries: List[Dict[str, Any]],
    chunk_index: int,
    chunk_start: str,
    chunk_end: str,
) -> Dict[str, Any]:
    if not chunk_entries:
        return {
            "chunk_index": chunk_index,
            "time_range": {"start": chunk_start, "end": chunk_end},
            "key_points": ["No transcript content available for this segment."],
            "evidence": [],
            "named_entities": [],
            "actions_or_recommendations": [],
        }

    sample_positions = sorted(set([0, len(chunk_entries) // 2, len(chunk_entries) - 1]))
    key_points: List[str] = []
    evidence: List[Dict[str, str]] = []

    for pos in sample_positions:
        entry = chunk_entries[pos]
        text = entry["text"].strip()
        if not text:
            continue
        point = text[:220]
        key_points.append(point)
        evidence.append(
            {
                "timestamp": format_timestamp(float(entry["start"])),
                "detail": text[:180],
            }
        )

    if not key_points:
        key_points = [chunk_entries[0]["text"][:220]]

    return {
        "chunk_index": chunk_index,
        "time_range": {"start": chunk_start, "end": chunk_end},
        "key_points": key_points[:6],
        "evidence": evidence[:6],
        "named_entities": [],
        "actions_or_recommendations": [],
    }


def summarize_chunk(
    chunk_entries: List[Dict[str, Any]],
    chunk_index: int,
    total_chunks: int,
    output_language: str,
    model_name: str,
    usage_report: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    chunk_start = format_timestamp(float(chunk_entries[0]["start"]))
    chunk_end_entry = chunk_entries[-1]
    chunk_end = format_timestamp(float(chunk_end_entry["start"]) + float(chunk_end_entry["duration"]))
    chunk_text = chunk_to_prompt_text(chunk_entries)

    user_prompt = f"""
You are extracting concise factual notes from a transcript chunk.
Target output language for the final summary is: {output_language}
Current chunk: {chunk_index}/{total_chunks} ({chunk_start} - {chunk_end})

Transcript chunk:
{chunk_text}

Return valid JSON only with this schema:
{{
  "chunk_index": {chunk_index},
  "time_range": {{"start": "{chunk_start}", "end": "{chunk_end}"}},
  "key_points": ["short factual point"],
  "evidence": [{{"timestamp": "mm:ss", "detail": "brief evidence"}}],
  "named_entities": ["term"],
  "actions_or_recommendations": ["item"]
}}

Rules:
- Use only information from this chunk.
- 4 to 8 key points max.
- 6 evidence items max.
- Keep each item short.
""".strip()

    raw_note = call_chat_completion(
        step_name=f"chunk_{chunk_index}_notes",
        model_name=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful research assistant. "
                    "Extract only grounded points, avoid speculation, and output strict JSON."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=MAP_MAX_TOKENS,
        usage_report=usage_report,
        reasoning_effort=MAP_REASONING_EFFORT,
        response_format={"type": "json_object"},
    )
    if not raw_note:
        print(
            f"[AI] step=chunk_{chunk_index}_notes falling back to heuristic notes "
            "due to empty model output."
        )
        return build_fallback_chunk_note(
            chunk_entries=chunk_entries,
            chunk_index=chunk_index,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        )

    parsed = extract_json_object(raw_note)
    if parsed:
        return parsed

    # Graceful fallback so one malformed chunk does not fail the whole pipeline.
    return {
        "chunk_index": chunk_index,
        "time_range": {"start": chunk_start, "end": chunk_end},
        "key_points": [line.strip("- ").strip() for line in raw_note.splitlines() if line.strip()][:8],
        "evidence": [],
        "named_entities": [],
        "actions_or_recommendations": [],
    }


def chunk_note_to_text(chunk_note: Dict[str, Any]) -> str:
    chunk_index = chunk_note.get("chunk_index", "?")
    time_range = chunk_note.get("time_range", {})
    start = time_range.get("start", "??:??")
    end = time_range.get("end", "??:??")

    lines = [f"Chunk {chunk_index} [{start} - {end}]"]

    key_points = chunk_note.get("key_points", [])[:8]
    for item in key_points:
        lines.append(f"- {item}")

    evidence_items = chunk_note.get("evidence", [])[:6]
    for item in evidence_items:
        if isinstance(item, dict):
            detail = item.get("detail", "")
            lines.append(f"  * {detail}")

    actions = chunk_note.get("actions_or_recommendations", [])[:4]
    if actions:
        lines.append("  Actions:")
        for action in actions:
            lines.append(f"  - {action}")

    entities = chunk_note.get("named_entities", [])[:8]
    if entities:
        lines.append(f"  Entities: {', '.join(entities)}")

    return "\n".join(lines)


def build_compact_notes_text(chunk_notes: List[Dict[str, Any]], max_chars: int = 45000) -> str:
    parts: List[str] = []
    total_chars = 0
    for note in chunk_notes:
        note_text = chunk_note_to_text(note)
        if total_chars + len(note_text) > max_chars:
            break
        parts.append(note_text)
        total_chars += len(note_text)
    return "\n\n".join(parts)


def fallback_plan(
    chunk_notes: List[Dict[str, Any]],
    target_output_tokens: int,
    route: str,
) -> Dict[str, Any]:
    section_count = 4 if route == "medium" else 6
    section_tokens = max(250, target_output_tokens // section_count)

    sections = []
    for i in range(section_count):
        sections.append(
            {
                "id": str(i + 1),
                "heading": f"Section {i + 1}",
                "goal": "Cover the most important points in this part of the video.",
                "source_chunks": [],
                "target_tokens": section_tokens,
            }
        )

    return {
        "title": "Video Summary",
        "summary_intent": "Comprehensive, factual summary with clear structure.",
        "sections": sections,
        "coverage_checks": ["Include key claims, evidence, and practical implications."],
    }


def build_plan(
    chunk_notes: List[Dict[str, Any]],
    route: str,
    output_language: str,
    target_output_tokens: int,
    model_name: str,
    usage_report: Dict[str, Any],
) -> Dict[str, Any]:
    notes_text = build_compact_notes_text(chunk_notes)

    if route == "medium":
        target_section_count = "4 to 6"
    else:
        target_section_count = "6 to 9"

    prompt = f"""
Create an execution plan for a final summary in {output_language}.

Evidence pack from transcript chunks:
{notes_text}

Return valid JSON only:
{{
  "title": "summary title",
  "summary_intent": "one sentence",
  "sections": [
    {{
      "id": "1",
      "heading": "section heading",
      "goal": "what this section should accomplish",
      "source_chunks": [1,2],
      "target_tokens": 500
    }}
  ],
  "coverage_checks": ["check 1", "check 2"]
}}

Rules:
- Build {target_section_count} sections.
- Total of section target_tokens should be close to {target_output_tokens}.
- Prioritize signal over verbosity.
- Keep source_chunks grounded in available chunk IDs.
""".strip()

    raw_plan = call_chat_completion(
        step_name="plan",
        model_name=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a planning assistant for long-form summarization. "
                    "Create token-efficient plans with explicit section objectives."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=PLAN_MAX_TOKENS,
        usage_report=usage_report,
        reasoning_effort=PLAN_REASONING_EFFORT,
        response_format={"type": "json_object"},
    )
    if not raw_plan:
        return fallback_plan(chunk_notes, target_output_tokens, route)

    parsed = extract_json_object(raw_plan)
    if parsed:
        return parsed

    return fallback_plan(chunk_notes, target_output_tokens, route)


def generate_short_summary(
    transcript_entries: List[Dict[str, Any]],
    output_language: str,
    target_output_tokens: int,
    model_name: str,
    usage_report: Dict[str, Any],
) -> Optional[str]:
    transcript_text = transcript_entries_to_plain_text(transcript_entries)
    prompt = f"""
Write the best possible summary in {output_language}.

Transcript:
{transcript_text}

Output requirements:
- Markdown output.
- Include `# Title`.
- Include `## Core Summary` with fluent prose paragraphs.
- Include `## Main Points`.
- Include `## Detailed Notes` with meaningful subheadings when needed.
- Include `## Practical Takeaways` only if there are actionable insights.
- Do not include inline timestamps or time ranges (for example `[09:13]` or `[09:13-10:11]`).
- Write fluent, natural prose that reads like a polished article.
- Do not use attribution phrases such as "the speaker says", "the speaker explains",
  "the video discusses", or "the transcript mentions".
- Write as direct notes from someone who listened carefully.
- Stay concise and avoid repetition.
- Aim for roughly {target_output_tokens} tokens.
""".strip()

    return call_chat_completion(
        step_name="short_summary",
        model_name=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert analyst creating faithful summaries. "
                    "Maximize insight density and keep factual grounding. "
                    "Never output inline timestamp markers. "
                    "Use direct declarative writing and avoid references to the speaker, transcript, or video."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=target_output_tokens,
        usage_report=usage_report,
        reasoning_effort=SHORT_REASONING_EFFORT,
    )


def synthesize_from_plan(
    plan: Dict[str, Any],
    chunk_notes: List[Dict[str, Any]],
    output_language: str,
    target_output_tokens: int,
    model_name: str,
    usage_report: Dict[str, Any],
) -> Optional[str]:
    notes_text = build_compact_notes_text(chunk_notes)
    plan_json = json.dumps(plan, ensure_ascii=False, indent=2)

    prompt = f"""
Create a high-quality final summary in {output_language}.

Execution plan:
{plan_json}

Evidence pack:
{notes_text}

Output requirements:
- Follow the plan's section order.
- Markdown output.
- Include `# Title`.
- Include `## Core Summary` with fluent prose paragraphs.
- Include each planned section as `## <Heading>`.
- Include `## Practical Takeaways` only if there are actionable insights.
- Do not include inline timestamps or time ranges (for example `[09:13]` or `[09:13-10:11]`).
- Write fluent, natural prose that reads like a polished article.
- Do not use attribution phrases such as "the speaker says", "the speaker explains",
  "the video discusses", or "the transcript mentions".
- Write as direct notes from someone who listened carefully.
- Avoid filler and repetition.
- Target around {target_output_tokens} tokens.
""".strip()

    return call_chat_completion(
        step_name="final_summary",
        model_name=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write precise, useful, professional summaries. "
                    "Keep claims grounded and optimize for clarity per token. "
                    "Never output inline timestamp markers. "
                    "Do not refer to a speaker, video, or transcript."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=target_output_tokens,
        usage_report=usage_report,
        reasoning_effort=FINAL_REASONING_EFFORT,
    )


def generate_summary(
    transcript_entries: List[Dict[str, Any]],
    output_language: str,
    quality_mode: str = DEFAULT_QUALITY,
) -> Tuple[Optional[str], Dict[str, Any]]:
    normalized_entries = normalize_transcript_entries(transcript_entries)
    if not normalized_entries:
        return None, {}

    transcript_tokens = transcript_token_estimate(normalized_entries)
    duration_minutes = transcript_duration_minutes(normalized_entries)
    route = choose_route(transcript_tokens)
    target_output_tokens = choose_target_output_tokens(transcript_tokens, duration_minutes, route)

    safe_quality_mode = quality_mode if quality_mode in QUALITY_MODES else DEFAULT_QUALITY
    models = choose_models(safe_quality_mode)

    print(
        f"Summarization route={route}, quality={safe_quality_mode}, "
        f"transcript_tokens~{transcript_tokens}, target_output_tokens={target_output_tokens}"
    )
    print(
        f"Models -> worker={models['worker']}, planner={models['planner']}, writer={models['writer']}"
    )

    usage_report = init_usage_report(
        quality_mode=safe_quality_mode,
        route=route,
        transcript_tokens=transcript_tokens,
        target_output_tokens=target_output_tokens,
    )

    if route == "short":
        summary = generate_short_summary(
            normalized_entries,
            output_language,
            target_output_tokens,
            models["writer"],
            usage_report,
        )
        return summary, usage_report

    chunk_target_tokens = choose_chunk_target_tokens(route)
    transcript_chunks = chunk_transcript(
        normalized_entries,
        target_tokens=chunk_target_tokens,
        max_chunks=MAX_CHUNKS,
    )
    print(f"Chunked transcript into {len(transcript_chunks)} chunks (target={chunk_target_tokens} tokens/chunk)")

    chunk_notes: List[Dict[str, Any]] = []
    total_chunks = len(transcript_chunks)
    for idx, chunk in enumerate(transcript_chunks, start=1):
        note = summarize_chunk(
            chunk_entries=chunk,
            chunk_index=idx,
            total_chunks=total_chunks,
            output_language=output_language,
            model_name=models["worker"],
            usage_report=usage_report,
        )
        if note:
            chunk_notes.append(note)

    if not chunk_notes:
        print("Error: Could not create chunk notes from transcript.")
        return None, usage_report

    plan = build_plan(
        chunk_notes=chunk_notes,
        route=route,
        output_language=output_language,
        target_output_tokens=target_output_tokens,
        model_name=models["planner"],
        usage_report=usage_report,
    )

    final_summary = synthesize_from_plan(
        plan=plan,
        chunk_notes=chunk_notes,
        output_language=output_language,
        target_output_tokens=target_output_tokens,
        model_name=models["writer"],
        usage_report=usage_report,
    )

    if not final_summary:
        print("[AI] final_summary failed; falling back to single-pass summary mode.")
        final_summary = generate_short_summary(
            transcript_entries=normalized_entries,
            output_language=output_language,
            target_output_tokens=target_output_tokens,
            model_name=models["writer"],
            usage_report=usage_report,
        )

    return final_summary, usage_report


def print_usage_report(usage_report: Dict[str, Any]) -> None:
    if not usage_report:
        return

    print(
        "Usage summary: "
        f"calls={usage_report['calls']}, "
        f"prompt_tokens={usage_report['prompt_tokens']}, "
        f"completion_tokens={usage_report['completion_tokens']}, "
        f"total_tokens={usage_report['total_tokens']}, "
        f"est_cost=${usage_report['estimated_cost_usd']:.4f}"
    )
