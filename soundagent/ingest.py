import shutil
import logging
from pathlib import Path

log = logging.getLogger("soundagent.ingest")

ALLOWED_EXTENSIONS = frozenset({
    ".wav", ".bwf", ".aiff", ".aif",
    ".flac", ".mp3", ".aac", ".m4a",
    ".ogg", ".opus",
})


def is_allowed(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def stage_file(src: Path, staging_dir: Path, hash_fragment: str = "") -> Path:
    """Atomically copy src into staging_dir. Returns the staging path.

    The caller is responsible for removing src from inbox after a
    successful stage + ffprobe, so a crash mid-copy leaves the original
    intact for the next tick.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    dest = staging_dir / src.name

    if dest.exists():
        stem = src.stem + (f"_{hash_fragment[:8]}" if hash_fragment else "_dup")
        dest = staging_dir / f"{stem}{src.suffix}"

    tmp = staging_dir / f".{dest.name}.tmp"
    shutil.copy2(src, tmp)
    tmp.rename(dest)
    return dest
