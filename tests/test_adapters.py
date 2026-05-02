import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soundagent.adapters import get_adapter
from soundagent.adapters.local import LocalAdapter, NetworkAdapter
from soundagent.config import Config, SourceConfig


def _cfg(root: Path) -> Config:
    cfg = MagicMock(spec=Config)
    cfg.library_root = root
    return cfg


def _source(name: str, stype: str, **opts) -> SourceConfig:
    return SourceConfig(name=name, type=stype, enabled=True, options=opts)


# ── LocalAdapter ─────────────────────────────────────────────────────────────

def test_local_collect_copies_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lib"
        inbox = root / "_inbox"
        inbox.mkdir(parents=True)

        src_dir = Path(tmp) / "source"
        src_dir.mkdir()
        (src_dir / "kick.wav").write_bytes(b"wav data")

        cfg = _cfg(root)
        source = _source("local", "local", path=str(src_dir))
        adapter = LocalAdapter(cfg, source)

        assert adapter.is_available()
        result = adapter.collect()
        assert len(result) == 1
        assert result[0].name == "kick.wav"
        assert result[0].parent == inbox


def test_local_collect_skips_dotfiles():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lib"
        inbox = root / "_inbox"
        inbox.mkdir(parents=True)

        src_dir = Path(tmp) / "source"
        src_dir.mkdir()
        (src_dir / ".DS_Store").write_bytes(b"junk")
        (src_dir / "snare.wav").write_bytes(b"wav")

        adapter = LocalAdapter(_cfg(root), _source("l", "local", path=str(src_dir)))
        result = adapter.collect()
        assert len(result) == 1
        assert result[0].name == "snare.wav"


def test_local_collect_same_dir_no_copy():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lib"
        inbox = root / "_inbox"
        inbox.mkdir(parents=True)
        (inbox / "file.wav").write_bytes(b"wav")

        adapter = LocalAdapter(_cfg(root), _source("l", "local", path=str(inbox)))
        result = adapter.collect()
        assert len(result) == 1
        assert result[0] == inbox / "file.wav"


def test_local_unavailable_path_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lib"
        (root / "_inbox").mkdir(parents=True)
        adapter = LocalAdapter(_cfg(root), _source("l", "local", path="/does/not/exist"))
        assert not adapter.is_available()
        assert adapter.collect() == []


def test_local_dry_run_copies_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lib"
        inbox = root / "_inbox"
        inbox.mkdir(parents=True)
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        (src_dir / "hi.wav").write_bytes(b"wav")

        adapter = LocalAdapter(_cfg(root), _source("l", "local", path=str(src_dir)))
        result = adapter.collect(dry_run=True)
        assert result == []
        assert not (inbox / "hi.wav").exists()


# ── NetworkAdapter ────────────────────────────────────────────────────────────

def test_network_skips_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lib"
        (root / "_inbox").mkdir(parents=True)
        adapter = NetworkAdapter(_cfg(root), _source("n", "network", path="/no/such/path"))
        assert not adapter.is_available()
        assert adapter.collect() == []


# ── Adapter factory ───────────────────────────────────────────────────────────

def test_get_adapter_unknown_type_raises():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(Path(tmp))
        source = _source("x", "ftp")
        with pytest.raises(ValueError, match="Unknown adapter type"):
            get_adapter(cfg, source)


def test_get_adapter_returns_correct_types():
    from soundagent.adapters.local import LocalAdapter, NetworkAdapter
    from soundagent.adapters.rclone import RcloneAdapter
    from soundagent.adapters.webdav import WebDAVAdapter

    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(Path(tmp))
        assert isinstance(get_adapter(cfg, _source("a", "local", path="/")), LocalAdapter)
        assert isinstance(get_adapter(cfg, _source("b", "network", path="/")), NetworkAdapter)
        assert isinstance(get_adapter(cfg, _source("c", "rclone", remote="r", remote_path="/")), RcloneAdapter)
        assert isinstance(get_adapter(cfg, _source("d", "webdav")), WebDAVAdapter)
