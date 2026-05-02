import tempfile
from pathlib import Path

import pytest

from soundagent.config import load_config

SAMPLE = """
library_root: /tmp/soundlibrary
basehead_import_path: /tmp/basehead
tick_interval: 60
log_level: DEBUG
sources:
  - name: local-inbox
    type: local
    path: /tmp/inbox
    enabled: true
  - name: nas-inbox
    type: network
    path: /mnt/nas/inbox
    enabled: false
"""


def _write_cfg(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.flush()
    return f.name


def test_load_basic():
    cfg = load_config(_write_cfg(SAMPLE))
    assert cfg.library_root == Path("/tmp/soundlibrary")
    assert cfg.tick_interval == 60
    assert cfg.log_level == "DEBUG"


def test_sources_parsed():
    cfg = load_config(_write_cfg(SAMPLE))
    assert len(cfg.sources) == 2
    local = cfg.sources[0]
    assert local.name == "local-inbox"
    assert local.type == "local"
    assert local.enabled is True
    assert cfg.sources[1].enabled is False


def test_source_options_preserved():
    cfg = load_config(_write_cfg(SAMPLE))
    assert cfg.sources[0].options["path"] == "/tmp/inbox"


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")


def test_missing_library_root_raises():
    bad = """
basehead_import_path: /tmp/b
sources: []
"""
    with pytest.raises(ValueError, match="library_root"):
        load_config(_write_cfg(bad))


def test_env_override(monkeypatch):
    monkeypatch.setenv("SOUNDAGENT_LIBRARY_ROOT", "/overridden")
    cfg = load_config(_write_cfg(SAMPLE))
    assert cfg.library_root == Path("/overridden")
