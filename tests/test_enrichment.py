import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soundagent.enrichment import (
    CONFIDENCE_THRESHOLD,
    EnrichmentCache,
    EnrichmentResult,
    _extract_json,
    _validate,
    enrich,
)
from soundagent.ffprobe import AudioMetadata

GOOD_RESPONSE = {
    "category": "sfx",
    "subcategory": "impacts",
    "description": "A heavy metal impact with long reverb.",
    "tags": ["metal", "impact", "reverb"],
    "mood": "tense",
    "energy": "high",
    "bpm": None,
    "key": None,
    "confidence": 0.92,
}

MOCK_META = AudioMetadata(
    duration_s=2.1,
    sample_rate=48000,
    bit_depth=24,
    channels=1,
    format="wav",
    codec="pcm_s24le",
    file_size=100000,
)


def _cfg(api_key: str = "test-key") -> MagicMock:
    cfg = MagicMock()
    cfg.anthropic_api_key = api_key
    return cfg


# ── EnrichmentCache ───────────────────────────────────────────────────────────

def test_cache_miss_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        assert cache.get("nonexistent") is None


def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        result = EnrichmentResult(**GOOD_RESPONSE, low_confidence=False)
        cache.set("abc123", result)

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
        cache.set("hash1", EnrichmentResult(**GOOD_RESPONSE, low_confidence=False))
        assert path.exists()
        data = json.loads(path.read_text())
        assert "hash1" in data


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
    low = {**GOOD_RESPONSE, "confidence": CONFIDENCE_THRESHOLD - 0.01}
    result = _validate(low)
    assert result.low_confidence is True


def test_validate_confidence_clamped():
    result = _validate({**GOOD_RESPONSE, "confidence": 1.5})
    assert result.confidence == 1.0


def test_validate_music_with_bpm():
    music = {
        **GOOD_RESPONSE,
        "category": "music",
        "subcategory": "loops",
        "bpm": 120.0,
        "key": "C minor",
    }
    result = _validate(music)
    assert result.bpm == 120.0
    assert result.key == "C minor"


# ── enrich() ─────────────────────────────────────────────────────────────────

def test_enrich_returns_cached_result():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        expected = EnrichmentResult(**GOOD_RESPONSE, low_confidence=False)
        cache.set("hash_abc", expected)

        with patch("soundagent.enrichment._call_api") as mock_api:
            result = enrich("kick.wav", "hash_abc", MOCK_META, _cfg(), cache)
            mock_api.assert_not_called()
            assert result.category == "sfx"


def test_enrich_calls_api_on_cache_miss():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        raw = json.dumps(GOOD_RESPONSE)

        with patch("soundagent.enrichment._call_api", return_value=raw):
            with patch("anthropic.Anthropic"):
                result = enrich("kick.wav", "new_hash", MOCK_META, _cfg(), cache)
        assert result.category == "sfx"


def test_enrich_stores_result_in_cache():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        raw = json.dumps(GOOD_RESPONSE)

        with patch("soundagent.enrichment._call_api", return_value=raw):
            with patch("anthropic.Anthropic"):
                enrich("kick.wav", "hash_xyz", MOCK_META, _cfg(), cache)

        assert cache.get("hash_xyz") is not None


def test_enrich_raises_without_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            enrich("kick.wav", "h", MOCK_META, _cfg(api_key=""), cache)


def test_enrich_raises_on_bad_json():
    with tempfile.TemporaryDirectory() as tmp:
        cache = EnrichmentCache(Path(tmp) / "cache.json")
        with patch("soundagent.enrichment._call_api", return_value="not json at all"):
            with patch("anthropic.Anthropic"):
                with pytest.raises(ValueError, match="Bad API response"):
                    enrich("kick.wav", "h2", MOCK_META, _cfg(), cache)
