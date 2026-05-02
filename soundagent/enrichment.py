"""
Claude enrichment pipeline.

Sends ffprobe metadata + filename (+ audio analysis results when available)
to Claude and returns structured tags. Results are cached by SHA-256 hash
so unchanged files are never re-sent.
"""

import json
import logging
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from soundagent.config import Config
from soundagent.ffprobe import AudioMetadata

if TYPE_CHECKING:
    from soundagent.audio_analysis.result import AnalysisResult

log = logging.getLogger("soundagent.enrichment")

CONFIDENCE_THRESHOLD = 0.70

VALID_SUBCATEGORIES: dict[str, set[str]] = {
    "field":     {"nature", "urban", "industrial", "interior"},
    "sfx":       {"impacts", "ambience", "foley", "designed"},
    "music":     {"loops", "stems", "beds", "stingers"},
    "broadcast": {"idents", "vo", "transitions"},
    "voice":     {"dialogue", "narration", "interview", "speech"},
    "ambience":  {"nature", "urban", "indoor", "mixed"},
}
VALID_CATEGORIES = set(VALID_SUBCATEGORIES)

_SYSTEM = (
    "You are a professional sound library metadata specialist with deep knowledge of "
    "UCS (Universal Category System) conventions and professional audio workflows. "
    "When audio analysis data is provided, treat it as ground truth from ML models "
    "that have listened to the actual audio — synthesise and interpret those detections "
    "rather than guessing from the filename alone. "
    "Return ONLY valid JSON — no markdown, no explanation, no code fences."
)


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(filename: str, meta: AudioMetadata, analysis_result: "AnalysisResult") -> str:
    lines = [
        "Analyse this audio file and return metadata as JSON.",
        "",
        "## File Information",
        f"Filename: {filename}",
        f"Duration: {meta.duration_s:.1f}s",
        f"Format: {meta.format} / {meta.codec}",
        f"Sample rate: {meta.sample_rate} Hz",
        f"Bit depth: {meta.bit_depth if meta.bit_depth else 'unknown'}",
        f"Channels: {meta.channels}",
    ]

    if not analysis_result.fallback_only:
        lines += [
            "",
            "## Audio Analysis Results",
            f"Content type (YAMNet): {analysis_result.content_type}",
        ]

        if analysis_result.yamnet_classes:
            lines.append(f"YAMNet top classes: {', '.join(analysis_result.yamnet_classes[:6])}")

        if analysis_result.audioclip_matches:
            matches_str = "; ".join(
                f"{m['prompt']} ({m['score']:.2f})"
                for m in analysis_result.audioclip_matches[:5]
            )
            lines.append(f"AudioCLIP matches: {matches_str}")

        if analysis_result.content_type == "speech" and analysis_result.whisper_summary:
            lines += [
                "",
                "## Speech Content (Whisper)",
                f"Language: {analysis_result.whisper_language or 'unknown'}",
                f"Content summary: {analysis_result.whisper_summary}",
            ]

        if analysis_result.content_type == "music":
            lines += ["", "## Music Analysis (Essentia)"]
            if analysis_result.essentia_bpm is not None:
                conf = (
                    f" (confidence: {analysis_result.essentia_bpm_confidence:.2f})"
                    if analysis_result.essentia_bpm_confidence is not None else ""
                )
                lines.append(f"BPM: {analysis_result.essentia_bpm:.1f}{conf}")
            if analysis_result.essentia_key:
                lines.append(f"Key: {analysis_result.essentia_key}")
            if analysis_result.essentia_mood:
                mood_str = ", ".join(f"{k}: {v:.2f}" for k, v in analysis_result.essentia_mood.items())
                lines.append(f"Mood scores: {mood_str}")
    else:
        lines += [
            "",
            "Note: No ML audio analysis was available for this file. "
            "Classify based on the filename and technical metadata only. "
            "Set enrichment_confidence lower to reflect this uncertainty.",
        ]

    lines += [
        "",
        "## Required Output Schema",
        'Return ONLY this JSON object:',
        '{',
        '  "category":             "<field|sfx|music|broadcast|voice|ambience>",',
        '  "subcategory":          "<subcategory from the list below>",',
        '  "description":          "<1–2 sentence description of the sound>",',
        '  "tags":                 ["<tag>", ...],',
        '  "mood":                 "<mood descriptor>",',
        '  "energy":               "<low|medium|high>",',
        '  "bpm":                  <number or null>,',
        '  "musical_key":          "<musical key or null>",',
        '  "enrichment_confidence": <0.0–1.0>,',
        '  "usage_suggestions":    ["<use case>", ...],',
        '  "notes":                "<any notable characteristics or null>",',
        '  "language":             "<ISO 639-1 code or null>"',
        '}',
        '',
        'Subcategory options per category:',
        '  field:     nature | urban | industrial | interior',
        '  sfx:       impacts | ambience | foley | designed',
        '  music:     loops | stems | beds | stingers',
        '  broadcast: idents | vo | transitions',
        '  voice:     dialogue | narration | interview | speech',
        '  ambience:  nature | urban | indoor | mixed',
        '',
        'enrichment_confidence: your certainty in this classification (1.0 = certain).',
        'bpm / musical_key: music files only; null for everything else.',
        'language: ISO 639-1 code for voice/speech files; null otherwise.',
    ]

    return "\n".join(lines)


# ── EnrichmentResult ──────────────────────────────────────────────────────────

@dataclass
class EnrichmentResult:
    category: str
    subcategory: str
    description: str
    tags: list[str]
    mood: str
    energy: str
    bpm: Optional[float]
    key: Optional[str]
    confidence: float
    low_confidence: bool   # True when confidence < CONFIDENCE_THRESHOLD
    content_type: Optional[str] = None
    usage_suggestions: list[str] = _field(default_factory=list)
    notes: Optional[str] = None
    language: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
            "tags": self.tags,
            "mood": self.mood,
            "energy": self.energy,
            "bpm": self.bpm,
            "key": self.key,
            "confidence": self.confidence,
            "low_confidence": self.low_confidence,
            "content_type": self.content_type,
            "usage_suggestions": self.usage_suggestions,
            "notes": self.notes,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EnrichmentResult":
        return cls(
            category=d["category"],
            subcategory=d["subcategory"],
            description=d["description"],
            tags=d["tags"],
            mood=d["mood"],
            energy=d["energy"],
            bpm=d["bpm"],
            key=d["key"],
            confidence=d["confidence"],
            low_confidence=d["low_confidence"],
            content_type=d.get("content_type"),
            usage_suggestions=d.get("usage_suggestions", []),
            notes=d.get("notes"),
            language=d.get("language"),
        )


# ── Cache ─────────────────────────────────────────────────────────────────────

class EnrichmentCache:
    def __init__(self, path: Path, run_on_existing: bool = False):
        self.path = path
        self.run_on_existing = run_on_existing
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"Could not load enrichment cache ({e}), starting fresh")

    def get(self, file_hash: str) -> Optional[EnrichmentResult]:
        entry = self._data.get(file_hash)
        if entry is None:
            return None
        if self.run_on_existing and "content_type" not in entry:
            return None  # force re-enrichment for pre-analysis cached results
        try:
            return EnrichmentResult.from_dict(entry)
        except (TypeError, KeyError):
            return None

    def set(self, file_hash: str, result: EnrichmentResult) -> None:
        self._data[file_hash] = result.to_dict()
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


# ── API call with retry ───────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.InternalServerError,
    )),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _call_api(client: anthropic.Anthropic, prompt: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[{
            "type": "text",
            "text": _SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── Response parsing + validation ─────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()
    return json.loads(text)


def _validate(data: dict) -> EnrichmentResult:
    required = {"category", "subcategory", "description", "tags", "mood", "energy", "enrichment_confidence"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"API response missing fields: {missing}")

    category = str(data["category"]).lower()
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category {category!r}; expected one of {sorted(VALID_CATEGORIES)}")

    subcategory = str(data["subcategory"]).lower()
    valid_subs = VALID_SUBCATEGORIES[category]
    if subcategory not in valid_subs:
        raise ValueError(f"Invalid subcategory {subcategory!r} for category {category!r}")

    confidence = float(data["enrichment_confidence"])
    confidence = max(0.0, min(1.0, confidence))

    return EnrichmentResult(
        category=category,
        subcategory=subcategory,
        description=str(data["description"]).strip(),
        tags=[str(t).lower().strip() for t in data.get("tags", [])],
        mood=str(data.get("mood", "")).strip(),
        energy=str(data.get("energy", "medium")).lower().strip(),
        bpm=float(data["bpm"]) if data.get("bpm") is not None else None,
        key=str(data["musical_key"]) if data.get("musical_key") is not None else None,
        confidence=confidence,
        low_confidence=confidence < CONFIDENCE_THRESHOLD,
        usage_suggestions=[str(s) for s in data.get("usage_suggestions", [])],
        notes=str(data["notes"]) if data.get("notes") is not None else None,
        language=str(data["language"]) if data.get("language") is not None else None,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def enrich(
    filename: str,
    file_hash: str,
    meta: AudioMetadata,
    analysis_result: "AnalysisResult",
    cfg: Config,
    cache: EnrichmentCache,
) -> EnrichmentResult:
    cached = cache.get(file_hash)
    if cached is not None:
        log.debug(f"Cache hit: {filename}")
        return cached

    if not cfg.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    prompt = _build_prompt(filename, meta, analysis_result)

    raw = _call_api(client, prompt)
    log.debug(f"Raw API response for {filename}: {raw[:200]}")

    try:
        data = _extract_json(raw)
        result = _validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Bad API response for {filename}: {e}\nRaw: {raw[:500]}")

    # Carry content_type from audio analysis into result when Claude didn't set it
    if result.content_type is None and not analysis_result.fallback_only:
        result.content_type = analysis_result.content_type

    cache.set(file_hash, result)

    level = "low_confidence" if result.low_confidence else f"{result.category}/{result.subcategory}"
    log.info(f"Enriched: {filename} → {level} (confidence={result.confidence:.2f})")
    return result
