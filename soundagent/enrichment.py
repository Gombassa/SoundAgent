"""
Claude enrichment pipeline.

Sends ffprobe metadata + filename to Claude and returns structured tags.
Results are cached by SHA-256 hash so unchanged files are never re-sent.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from soundagent.config import Config
from soundagent.ffprobe import AudioMetadata

log = logging.getLogger("soundagent.enrichment")

CONFIDENCE_THRESHOLD = 0.70

VALID_SUBCATEGORIES: dict[str, set[str]] = {
    "field":     {"nature", "urban", "industrial", "interior"},
    "sfx":       {"impacts", "ambience", "foley", "designed"},
    "music":     {"loops", "stems", "beds", "stingers"},
    "broadcast": {"idents", "vo", "transitions"},
}
VALID_CATEGORIES = set(VALID_SUBCATEGORIES)

_SYSTEM = (
    "You are a professional sound library metadata specialist. "
    "Analyse the audio file information provided and return ONLY valid JSON — "
    "no markdown, no explanation, no code fences."
)

_PROMPT = """\
Analyse this audio file and return metadata as JSON.

File: {filename}
Duration: {duration_s:.1f}s
Format: {format} / {codec}
Sample rate: {sample_rate} Hz
Bit depth: {bit_depth}
Channels: {channels}

Return ONLY this JSON object:
{{
  "category":    "<field|sfx|music|broadcast>",
  "subcategory": "<subcategory from the list below>",
  "description": "<1–2 sentence description of the sound>",
  "tags":        ["<tag>", ...],
  "mood":        "<mood descriptor>",
  "energy":      "<low|medium|high>",
  "bpm":         <number or null>,
  "key":         "<musical key or null>",
  "confidence":  <0.0–1.0>
}}

Subcategory options per category:
  field:     nature | urban | industrial | interior
  sfx:       impacts | ambience | foley | designed
  music:     loops | stems | beds | stingers
  broadcast: idents | vo | transitions

confidence: your certainty in this classification (1.0 = certain).
bpm / key:  music files only; null for everything else.\
"""


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
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EnrichmentResult":
        return cls(**d)


# ── Cache ─────────────────────────────────────────────────────────────────────

class EnrichmentCache:
    def __init__(self, path: Path):
        self.path = path
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
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": _SYSTEM,
            "cache_control": {"type": "ephemeral"},  # cache system prompt across batch
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── Response parsing + validation ─────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    text = raw.strip()
    # Strip markdown code fences if Claude adds them despite instructions
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()
    return json.loads(text)


def _validate(data: dict) -> EnrichmentResult:
    required = {"category", "subcategory", "description", "tags", "mood", "energy", "confidence"}
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

    confidence = float(data["confidence"])
    confidence = max(0.0, min(1.0, confidence))

    return EnrichmentResult(
        category=category,
        subcategory=subcategory,
        description=str(data["description"]).strip(),
        tags=[str(t).lower().strip() for t in data.get("tags", [])],
        mood=str(data.get("mood", "")).strip(),
        energy=str(data.get("energy", "medium")).lower().strip(),
        bpm=float(data["bpm"]) if data.get("bpm") is not None else None,
        key=str(data["key"]) if data.get("key") is not None else None,
        confidence=confidence,
        low_confidence=confidence < CONFIDENCE_THRESHOLD,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def enrich(
    filename: str,
    file_hash: str,
    meta: AudioMetadata,
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
    prompt = _PROMPT.format(
        filename=filename,
        duration_s=meta.duration_s,
        format=meta.format,
        codec=meta.codec,
        sample_rate=meta.sample_rate,
        bit_depth=meta.bit_depth if meta.bit_depth else "unknown",
        channels=meta.channels,
    )

    raw = _call_api(client, prompt)
    log.debug(f"Raw API response for {filename}: {raw[:200]}")

    try:
        data = _extract_json(raw)
        result = _validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Bad API response for {filename}: {e}\nRaw: {raw[:500]}")

    cache.set(file_hash, result)

    level = "low_confidence" if result.low_confidence else f"{result.category}/{result.subcategory}"
    log.info(f"Enriched: {filename} → {level} (confidence={result.confidence:.2f})")
    return result
