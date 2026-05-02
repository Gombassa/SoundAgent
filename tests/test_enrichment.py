import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soundagent.enrichment import (
    CONFIDENCE_THRESHOLD,
    EnrichmentCache,
    EnrichmentResult,
    _build_prompt,
    _extract_json,
    _validate,
    enrich,
)
from soundagent.ffprobe import AudioMetadata
from soundagent.audio_analysis.result import AnalysisResult

# Claude API response shape (P7: enrichment_confidence, musical_key)
GOOD_RESPONSE = {
    "category": "sfx",
    "subcategory": "impacts",
    "description": "A heavy metal impact with long reverb.",
    "tags": ["metal", "impact", "reverb"],
    "mood": "tense",
    "energy": "high",
    "bpm": None,
    "musical_key": None,
    "enrichment_confidence": 0.92,
    "usage_suggestions": ["trailer hits", "impact accents"],
    "notes": None,
    "language": None,
}

# Expected EnrichmentResult matching GOOD_RESPONSE
GOOD_RESULT = EnrichmentResult(
    category="sfx",
    subcategory="impacts",
    description="A heavy metal impact with long reverb.",
    tags=["metal", "impact", "reverb"],
    mood="tense",
    energy="high",
    bpm=None,
    key=None,
    confidence=0.92,
    low_confidence=False,
    usage_suggestions=["trailer hits", "impact accents"],
    notes=None,
    language=None,
)

MOCK_META = AudioMetadata(
    duration_s=2.1,
    sample_rate=48000,
    bit_depth=24,
    channels=1,
    format="wav",
    codec="pcm_s24le",
    file_size=100000,
)

MOCK_ANALYSIS = AnalysisResult.fallback("test_hash")


def _cfg(api_key: str = "test-key") -> MagicMock:
    cfg = MagicMock()
    cfg.anthropic_api_key = api_key
    cfg.audio_analysis = {}
    return cfg


# ── EnrichmentCache ───────────────────────────────────────────────────────────

def test_cache_miss_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        assert cache.get("nonexistent") is None


def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        cache.set("abc123", GOOD_RESULT)

        cache2 = EnrichmentCache(Path(tmp) / "cache.json")
        loaded = cache2.get("abc123")
        assert loaded is not None
        assert loaded.category == "sfx"
        assert loaded.subcategory == "impacts"
        assert loaded.confidence == 0.92


def test_cache_persists_to_disk():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        cache = EnrichmentCache(path)
        cache.set("hash1", GOOD_RESULT)
        assert path.exists()
        data = json.loads(path.read_text())
        assert "hash1" in data


def test_cache_run_on_existing_invalidates_no_content_type():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cache.json"
        # Write an old-style cache entry without content_type
        old_entry = GOOD_RESULT.to_dict()
        del old_entry["content_type"]
        path.write_text(json.dumps({"oldhash": old_entry}))

        cache = EnrichmentCache(path, run_on_existing=True)
        assert cache.get("oldhash") is None   # forced re-enrichment

        cache2 = EnrichmentCache(path, run_on_existing=False)
        assert cache2.get("oldhash") is not None  # normal load


# ── _extract_json ─────────────────────────────────────────────────────────────

def test_extract_json_plain():
    raw = json.dumps(GOOD_RESPONSE)
    assert _extract_json(raw) == GOOD_RESPONSE


def test_extract_json_strips_code_fences():
    raw = f"```json\n{json.dumps(GOOD_RESPONSE)}\n```"
    assert _extract_json(raw) == GOOD_RESPONSE


# ── _validate ─────────────────────────────────────────────────────────────────

def test_validate_good_response():
    result = _validate(GOOD_RESPONSE)
    assert result.category == "sfx"
    assert result.subcategory == "impacts"
    assert result.low_confidence is False


def test_validate_invalid_category_raises():
    bad = {**GOOD_RESPONSE, "category": "zap"}
    with pytest.raises(ValueError, match="Invalid category"):
        _validate(bad)


def test_validate_invalid_subcategory_raises():
    bad = {**GOOD_RESPONSE, "subcategory": "explosions"}
    with pytest.raises(ValueError, match="Invalid subcategory"):
        _validate(bad)


def test_validate_missing_field_raises():
    bad = {k: v for k, v in GOOD_RESPONSE.items() if k != "description"}
    with pytest.raises(ValueError, match="missing fields"):
        _validate(bad)


def test_validate_low_confidence_flagged():
    low = {**GOOD_RESPONSE, "enrichment_confidence": CONFIDENCE_THRESHOLD - 0.01}
    result = _validate(low)
    assert result.low_confidence is True


def test_validate_confidence_clamped():
    result = _validate({**GOOD_RESPONSE, "enrichment_confidence": 1.5})
    assert result.confidence == 1.0


def test_validate_music_with_bpm():
    music = {
        **GOOD_RESPONSE,
        "category": "music",
        "subcategory": "loops",
        "bpm": 120.0,
        "musical_key": "C minor",
    }
    result = _validate(music)
    assert result.bpm == 120.0
    assert result.key == "C minor"


def test_validate_voice_category():
    voice = {
        **GOOD_RESPONSE,
        "category": "voice",
        "subcategory": "narration",
        "language": "en",
    }
    result = _validate(voice)
    assert result.category == "voice"
    assert result.subcategory == "narration"
    assert result.language == "en"


def test_validate_ambience_category():
    amb = {**GOOD_RESPONSE, "category": "ambience", "subcategory": "urban"}
    result = _validate(amb)
    assert result.category == "ambience"


def test_validate_usage_suggestions_and_notes():
    data = {
        **GOOD_RESPONSE,
        "usage_suggestions": ["score underlay", "game ambience"],
        "notes": "Contains a subtle low-frequency rumble.",
    }
    result = _validate(data)
    assert result.usage_suggestions == ["score underlay", "game ambience"]
    assert result.notes == "Contains a subtle low-frequency rumble."


# ── _build_prompt ─────────────────────────────────────────────────────────────

def test_build_prompt_includes_yamnet_when_not_fallback():
    analysis = AnalysisResult(
        file_hash="h",
        fallback_only=False,
        content_type="sfx_or_field",
        yamnet_classes=["Gunshot", "Explosion"],
        audioclip_matches=[{"prompt": "explosion", "score": 0.85}],
    )
    prompt = _build_prompt("bang.wav", MOCK_META, analysis)
    assert "YAMNet" in prompt
    assert "Gunshot" in prompt
    assert "explosion" in prompt


def test_build_prompt_fallback_note_when_fallback_only():
    analysis = AnalysisResult.fallback("h")
    prompt = _build_prompt("mystery.wav", MOCK_META, analysis)
    assert "No ML audio analysis" in prompt
    assert "YAMNet" not in prompt


def test_build_prompt_includes_whisper_for_speech():
    analysis = AnalysisResult(
        file_hash="h",
        fallback_only=False,
        content_type="speech",
        whisper_language="en",
        whisper_summary="A person describes a forest walk.",
    )
    prompt = _build_prompt("narration.wav", MOCK_META, analysis)
    assert "Whisper" in prompt
    assert "forest walk" in prompt


def test_build_prompt_includes_essentia_for_music():
    analysis = AnalysisResult(
        file_hash="h",
        fallback_only=False,
        content_type="music",
        essentia_bpm=128.0,
        essentia_key="A minor",
    )
    prompt = _build_prompt("loop.wav", MOCK_META, analysis)
    assert "Essentia" in prompt
    assert "128.0" in prompt
    assert "A minor" in prompt


# ── enrich() ─────────────────────────────────────────────────────────────────

def test_enrich_returns_cached_result():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        cache.set("hash_abc", GOOD_RESULT)

        with patch("soundagent.enrichment._call_api") as mock_api:
            result = enrich("kick.wav", "hash_abc", MOCK_META, MOCK_ANALYSIS, _cfg(), cache)
            mock_api.assert_not_called()
            assert result.category == "sfx"


def test_enrich_calls_api_on_cache_miss():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        raw = json.dumps(GOOD_RESPONSE)

        with patch("soundagent.enrichment._call_api", return_value=raw):
            with patch("anthropic.Anthropic"):
                result = enrich("kick.wav", "new_hash", MOCK_META, MOCK_ANALYSIS, _cfg(), cache)
        assert result.category == "sfx"


def test_enrich_stores_result_in_cache():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        raw = json.dumps(GOOD_RESPONSE)

        with patch("soundagent.enrichment._call_api", return_value=raw):
            with patch("anthropic.Anthropic"):
                enrich("kick.wav", "hash_xyz", MOCK_META, MOCK_ANALYSIS, _cfg(), cache)

        assert cache.get("hash_xyz") is not None


def test_enrich_raises_without_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            enrich("kick.wav", "h", MOCK_META, MOCK_ANALYSIS, _cfg(api_key=""), cache)


def test_enrich_raises_on_bad_json():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        with patch("soundagent.enrichment._call_api", return_value="not json at all"):
            with patch("anthropic.Anthropic"):
                with pytest.raises(ValueError, match="Bad API response"):
                    enrich("kick.wav", "h2", MOCK_META, MOCK_ANALYSIS, _cfg(), cache)
