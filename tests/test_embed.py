import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soundagent.embed import build_ixml, embed, write_xmp_sidecar, _EXT_WAV, _EXT_MP3, _EXT_FLAC
from soundagent.ucs import UCSFields


def _ucs(**kwargs) -> UCSFields:
    defaults = dict(
        category="SFX",
        subcategory="IMPACTS",
        cat_id="SFX-IMPA",
        fx_name="Metal Hit",
        description="A heavy metal impact.",
        keywords="metal, impact",
        mood="tense",
        energy="high",
        bpm=None,
        key=None,
    )
    return UCSFields(**{**defaults, **kwargs})


# ── iXML builder ──────────────────────────────────────────────────────────────

def test_build_ixml_contains_required_fields():
    xml = build_ixml(_ucs())
    assert "<IXML>" in xml
    assert "<USER>" in xml
    assert "SFX-IMPA" in xml
    assert "Metal Hit" in xml
    assert "IMPACTS" in xml


def test_build_ixml_includes_bpm_when_set():
    xml = build_ixml(_ucs(bpm=120.0))
    assert "<BPM>120</BPM>" in xml


def test_build_ixml_excludes_bpm_when_none():
    xml = build_ixml(_ucs(bpm=None))
    assert "<BPM>" not in xml


def test_build_ixml_includes_key_when_set():
    xml = build_ixml(_ucs(key="C minor"))
    assert "C minor" in xml


def test_build_ixml_is_valid_xml():
    import xml.etree.ElementTree as ET
    xml = build_ixml(_ucs())
    # Strip the XML declaration for ET parsing
    body = xml.split("\n", 1)[1] if xml.startswith("<?xml") else xml
    ET.fromstring(body)   # raises if invalid


# ── XMP sidecar ───────────────────────────────────────────────────────────────

def test_write_xmp_sidecar_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sound.ogg"
        path.write_bytes(b"fake")
        xmp = write_xmp_sidecar(path, _ucs())
        assert xmp.exists()
        assert xmp.suffix == ".xmp"


def test_write_xmp_sidecar_contains_fields():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sound.ogg"
        path.write_bytes(b"fake")
        xmp = write_xmp_sidecar(path, _ucs())
        content = xmp.read_text()
        assert "SFX-IMPA" in content
        assert "Metal Hit" in content
        assert "tense" in content


def test_write_xmp_sidecar_escapes_special_chars():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sound.ogg"
        path.write_bytes(b"fake")
        u = _ucs(description='Sound with <special> & "chars"')
        xmp = write_xmp_sidecar(path, u)
        content = xmp.read_text()
        assert "&amp;" in content or "&lt;" in content   # XML-escaped


# ── WAV embed dispatch ────────────────────────────────────────────────────────

def test_embed_wav_calls_bwfmetaedit():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sound.wav"
        path.write_bytes(b"fake wav")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            from soundagent.embed import _embed_wav
            _embed_wav(path, _ucs())
            assert mock_run.call_count == 2   # iXML + BEXT


def test_embed_wav_falls_back_to_xmp_when_bwfmetaedit_missing():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sound.wav"
        path.write_bytes(b"fake wav")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            from soundagent.embed import _embed_wav
            _embed_wav(path, _ucs())
        xmp = Path(tmp) / "sound.wav.xmp"
        assert xmp.exists()


# ── embed() dispatch ──────────────────────────────────────────────────────────

def test_embed_unknown_ext_writes_xmp():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sound.opus"
        path.write_bytes(b"fake opus")
        embed(path, _ucs())
        assert (Path(tmp) / "sound.opus.xmp").exists()


def test_embed_wav_dispatches_to_wav_handler():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.wav"
        path.write_bytes(b"fake")
        with patch("soundagent.embed._embed_wav") as mock:
            embed(path, _ucs())
            mock.assert_called_once_with(path, _ucs(), None)


def test_embed_mp3_dispatches_to_mp3_handler():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.mp3"
        path.write_bytes(b"fake")
        with patch("soundagent.embed._embed_mp3") as mock:
            embed(path, _ucs())
            mock.assert_called_once()


def test_embed_flac_dispatches_to_flac_handler():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.flac"
        path.write_bytes(b"fake")
        with patch("soundagent.embed._embed_flac") as mock:
            embed(path, _ucs())
            mock.assert_called_once()
