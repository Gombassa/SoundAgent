"""
Enrichment pipeline — sends ffprobe metadata + audio analysis results to an
LLM provider (Ollama/Mistral by default, Claude API as alternative) and returns
structured tags. Results are cached by SHA-256 hash.

Provider is selected via config.yaml:
    enrichment:
      provider: ollama   # ollama | claude
"""

import json
import logging
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import anthropic
import requests
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
    "You are a professional sound library metadata specialist. "
    "Treat audio analysis data as ground truth from ML models — synthesise it rather than "
    "guessing from the filename alone. "
    "Return ONLY valid JSON — no markdown, no explanation, no code fences. "
    "For suggested_filename: UCS code + slug only, e.g. WTHR_rain-woodland-wind-light. "
    "No sample rate, bit depth, extension, or index numbers."
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
                f"{m['tag']} [{m.get('category', '')}] ({m['score']:.2f})"
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
            has_essentia = (
                analysis_result.essentia_bpm is not None or analysis_result.essentia_key
            )
            if has_essentia:
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

            if analysis_result.librosa_bpm is not None:
                lines += ["", "## Music Analysis (librosa — Windows)"]
                conf = (
                    f" (confidence: {analysis_result.librosa_bpm_confidence:.1f})"
                    if analysis_result.librosa_bpm_confidence is not None else ""
                )
                lines.append(f"BPM: {analysis_result.librosa_bpm:.1f}{conf}")
                if analysis_result.librosa_key:
                    lines.append(f"Key: {analysis_result.librosa_key}")
                if analysis_result.librosa_dynamic_complexity is not None:
                    lines.append(f"Dynamic complexity: {analysis_result.librosa_dynamic_complexity:.3f}")
                if analysis_result.librosa_spectral_centroid is not None:
                    lines.append(f"Spectral brightness: {analysis_result.librosa_spectral_centroid:.1f} Hz (mean)")
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
        '  "language":             "<ISO 639-1 code or null>",',
        '  "suggested_filename":   "<UCS code + slug only e.g. WTHR_rain-woodland-wind-light>"',
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
    suggested_filename: Optional[str] = None
    original_filename: str = ""

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
            "suggested_filename": self.suggested_filename,
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
            suggested_filename=d.get("suggested_filename"),
        )


# ── Analysis fingerprint helpers ──────────────────────────────────────────────

def _analysis_fingerprint(analysis_result: "AnalysisResult") -> dict:
    return {
        "models_run": sorted(analysis_result.models_run),
        "yamnet_top": analysis_result.yamnet_classes[0] if analysis_result.yamnet_classes else None,
    }


def _fingerprints_match(stored: dict, current: dict) -> bool:
    return (
        stored.get("models_run") == current.get("models_run")
        and stored.get("yamnet_top") == current.get("yamnet_top")
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

    def set(self, file_hash: str, result: EnrichmentResult, analysis_result: "AnalysisResult" = None) -> None:
        entry = result.to_dict()
        if analysis_result is not None:
            entry["_fingerprint"] = _analysis_fingerprint(analysis_result)
        self._data[file_hash] = entry
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


# ── Provider implementations ──────────────────────────────────────────────────

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
def _call_claude(client: anthropic.Anthropic, prompt: str) -> str:
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


def _call_ollama(ollama_url: str, model: str, prompt: str) -> str:
    url = f"{ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _call_provider(prompt: str, cfg) -> str:
    enrichment_cfg = cfg.enrichment
    provider = enrichment_cfg.get("provider", "ollama")

    if provider == "ollama":
        ollama_url = enrichment_cfg.get("ollama_url", "http://localhost:11434")
        model = enrichment_cfg.get("ollama_model", "mistral")
        try:
            return _call_ollama(ollama_url, model, prompt)
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning(f"Ollama unreachable at {ollama_url}: {exc}")
            if cfg.anthropic_api_key:
                log.info("Falling back to Claude API")
                client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
                return _call_claude(client, prompt)
            raise RuntimeError(
                "Ollama unreachable and no ANTHROPIC_API_KEY configured"
            ) from exc

    if provider == "claude":
        if not cfg.anthropic_api_key:
            raise RuntimeError("enrichment provider=claude but ANTHROPIC_API_KEY is not set")
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        return _call_claude(client, prompt)

    raise ValueError(f"Unknown enrichment provider: {provider!r}")


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

    suggested_raw = data.get("suggested_filename")
    suggested_filename = suggested_raw.strip() if isinstance(suggested_raw, str) and suggested_raw.strip() else None

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
        suggested_filename=suggested_filename,
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
        cached.original_filename = filename
        return cached

    # Analysis-unchanged shortcut: when run_on_existing forces a cache bypass,
    # avoid a Claude call if the analysis produced the same result as last time.
    if cache.run_on_existing:
        stored_entry = cache._data.get(file_hash)
        if stored_entry is not None:
            stored_fp = stored_entry.get("_fingerprint")
            if stored_fp is not None and _fingerprints_match(stored_fp, _analysis_fingerprint(analysis_result)):
                try:
                    result = EnrichmentResult.from_dict(stored_entry)
                    result.original_filename = filename
                    log.info(f"{filename} analysis unchanged — reusing cached enrichment")
                    return result
                except (TypeError, KeyError):
                    pass

    prompt = _build_prompt(filename, meta, analysis_result)
    raw = _call_provider(prompt, cfg)
    log.debug(f"Raw response for {filename}: {raw[:200]}")

    try:
        data = _extract_json(raw)
        result = _validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Bad API response for {filename}: {e}\nRaw: {raw[:500]}")

    # Carry content_type from audio analysis into result when Claude didn't set it
    if result.content_type is None and not analysis_result.fallback_only:
        result.content_type = analysis_result.content_type

    cache.set(file_hash, result, analysis_result)
    result.original_filename = filename

    level = "low_confidence" if result.low_confidence else f"{result.category}/{result.subcategory}"
    log.info(f"Enriched: {filename} → {level} (confidence={result.confidence:.2f})")
    return result
