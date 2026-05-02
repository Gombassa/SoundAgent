import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soundagent.enrichment import EnrichmentResult
from soundagent.router import _read_sidecar, _resolve_collision, deliver, route


def _cfg(root: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.library_root = root
    cfg.basehead_import_path = root / "_basehead_import"
    return cfg


def _result(category="sfx", subcategory="impacts", confidence=0.9, low_confidence=False) -> EnrichmentResult:
    return EnrichmentResult(
        category=category, subcategory=subcategory,
        description="A sound.", tags=["tag"],
        mood="neutral", energy="medium",
        bpm=None, key=None,
        confidence=confidence, low_confidence=low_confidence,
    )


def _staged_file(tmp: str, name: str = "kick.wav") -> Path:
    p = Path(tmp) / "_staging" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"fake audio")
    return p


# ── route() ───────────────────────────────────────────────────────────────────

def test_route_normal_goes_to_category_subfolder():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        decision = route(staging, _result("sfx", "impacts"), _cfg(root))
        assert decision.library_dest.parent == root / "sfx" / "impacts"
        assert not decision.is_unclassified
        assert not decision.override_used


def test_route_low_confidence_goes_to_unclassified():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        result = _result(confidence=0.5, low_confidence=True)
        decision = route(staging, result, _cfg(root))
        assert decision.library_dest.parent == root / "unclassified"
        assert decision.is_unclassified


def test_route_sidecar_override_wins_over_category():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        sidecar = staging.with_suffix(staging.suffix + ".soundagent.json")
        sidecar.write_text(json.dumps({"destination": "broadcast/idents"}))

        decision = route(staging, _result("sfx", "impacts"), _cfg(root))
        assert decision.library_dest.parent == root / "broadcast" / "idents"
        assert decision.override_used
        assert not decision.is_unclassified


def test_route_sidecar_override_wins_over_low_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        sidecar = staging.with_suffix(staging.suffix + ".soundagent.json")
        sidecar.write_text(json.dumps({"destination": "field/nature"}))

        result = _result(confidence=0.3, low_confidence=True)
        decision = route(staging, result, _cfg(root))
        assert decision.library_dest.parent == root / "field" / "nature"
        assert decision.override_used
        assert not decision.is_unclassified


def test_route_creates_destination_dir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        decision = route(staging, _result("music", "loops"), _cfg(root))
        assert decision.library_dest.parent.exists()


def test_route_basehead_dest_uses_import_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        decision = route(staging, _result(), _cfg(root))
        assert decision.basehead_dest.parent == root / "_basehead_import"


# ── deliver() ────────────────────────────────────────────────────────────────

def test_deliver_moves_file_to_library():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        decision = route(staging, _result(), _cfg(root))
        final = deliver(staging, decision, "abc123")
        assert final.exists()
        assert not staging.exists()


def test_deliver_copies_to_basehead_folder():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        decision = route(staging, _result(), _cfg(root))
        deliver(staging, decision, "abc123")
        assert decision.basehead_dest.parent.exists()
        bh_files = list(decision.basehead_dest.parent.iterdir())
        assert len(bh_files) == 1


def test_deliver_dry_run_moves_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        decision = route(staging, _result(), _cfg(root))
        deliver(staging, decision, "abc123", dry_run=True)
        assert staging.exists()
        assert not decision.library_dest.exists()


def test_deliver_collision_appends_hash():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging = _staged_file(tmp)
        decision = route(staging, _result("sfx", "impacts"), _cfg(root))
        # Pre-create file at destination to force collision
        decision.library_dest.parent.mkdir(parents=True, exist_ok=True)
        decision.library_dest.write_bytes(b"existing")

        final = deliver(staging, decision, "deadbeef12345678")
        assert "deadbeef" in final.name
        assert final != decision.library_dest


# ── helpers ───────────────────────────────────────────────────────────────────

def test_resolve_collision_no_conflict():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sound.wav"
        assert _resolve_collision(p) == p


def test_resolve_collision_appends_hash_fragment():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sound.wav"
        p.write_bytes(b"x")
        result = _resolve_collision(p, "abcdef1234567890")
        assert result.name == "sound_abcdef12.wav"


def test_read_sidecar_returns_none_when_absent():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sound.wav"
        p.write_bytes(b"x")
        assert _read_sidecar(p) is None


def test_read_sidecar_returns_destination():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sound.wav"
        p.write_bytes(b"x")
        sidecar = p.with_suffix(p.suffix + ".soundagent.json")
        sidecar.write_text(json.dumps({"destination": "sfx/designed"}))
        assert _read_sidecar(p) == "sfx/designed"


def test_read_sidecar_bad_json_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sound.wav"
        p.write_bytes(b"x")
        sidecar = p.with_suffix(p.suffix + ".soundagent.json")
        sidecar.write_text("not json {{{")
        assert _read_sidecar(p) is None


def test_read_sidecar_empty_destination_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sound.wav"
        p.write_bytes(b"x")
        sidecar = p.with_suffix(p.suffix + ".soundagent.json")
        sidecar.write_text(json.dumps({"destination": ""}))
        assert _read_sidecar(p) is None
