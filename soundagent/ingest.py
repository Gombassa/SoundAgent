import shutil
import logging
from pathlib import Path

log = logging.getLogger("soundagent.ingest")

ALLOWED_EXTENSIONS = frozenset({
    ".wav", ".bwf", ".aiff", ".aif",
    ".flac", ".mp3", ".aac", ".m4a",
    ".ogg", ".opus",
})

# DAW-generated sidecar and session files — silently discarded, never treated as errors.
SIDECAR_EXTENSIONS = frozenset({
    # Peak / waveform display cache
    ".pkf",   # Adobe Audition
    ".sfk",   # Sony Sound Forge / Wavelab
    ".wfm",   # Avid Pro Tools waveform cache
    ".asd",   # Ableton Live waveform analysis cache
    # DAW session / project files
    ".sesx",  # Adobe Audition session
    ".aup",   # Audacity project (XML)
    ".aup3",  # Audacity project (SQLite)
    ".ptx",   # Avid Pro Tools session (v8+)
    ".ptf",   # Avid Pro Tools session (v5–7)
    ".pts",   # Avid Pro Tools session settings
})


def is_allowed(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def is_sidecar(path: Path) -> bool:
    return path.suffix.lower() in SIDECAR_EXTENSIONS


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
    tmp.replace(dest)
    return dest
