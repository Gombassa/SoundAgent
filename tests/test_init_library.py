import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from soundagent.init_library import init_library, SUBDIRS


def _cfg(root: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.library_root = root
    return cfg


def test_creates_all_subdirs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "SoundLibrary"
        init_library(_cfg(root))
        for subdir in SUBDIRS:
            assert (root / subdir).exists(), f"Missing: {subdir}"


def test_dry_run_creates_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "SoundLibrary"
        init_library(_cfg(root), dry_run=True)
        assert not root.exists()


def test_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "SoundLibrary"
        init_library(_cfg(root))
        init_library(_cfg(root))   # second call must not raise
        assert (root / "_inbox").exists()
