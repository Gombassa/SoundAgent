import tempfile
from pathlib import Path

import pytest

from soundagent.ingest import is_allowed, stage_file, ALLOWED_EXTENSIONS


def test_allowed_extensions():
    for ext in ALLOWED_EXTENSIONS:
        assert is_allowed(Path(f"sound{ext}"))


def test_rejected_extensions():
    for ext in [".txt", ".pdf", ".exe", ".zip", ".jpg"]:
        assert not is_allowed(Path(f"file{ext}"))


def test_stage_file_copies():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "sound.wav"
        src.write_bytes(b"fake wav")
        staging = Path(tmp) / "staging"
        result = stage_file(src, staging)
        assert result.exists()
        assert result.read_bytes() == b"fake wav"
        assert src.exists()   # caller removes src, not stage_file


def test_stage_file_collision_appends_hash():
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        staging.mkdir()
        (staging / "sound.wav").write_bytes(b"existing")

        src = Path(tmp) / "sound.wav"
        src.write_bytes(b"new content")
        result = stage_file(src, staging, hash_fragment="abcdef1234567890")
        assert result.name != "sound.wav"
        assert "abcdef12" in result.name


def test_stage_file_creates_staging_dir():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "a.flac"
        src.write_bytes(b"flac")
        staging = Path(tmp) / "deep" / "staging"
        stage_file(src, staging)
        assert staging.exists()
