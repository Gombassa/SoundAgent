"""
soundagent/renamer.py

Hybrid UCS+slug filename generation.
Format: {UCS_CATID}_{descriptive-slug}_{sample_rate}k{bit_depth}b.{ext}
"""

import logging
import re
from pathlib import Path

from soundagent.ffprobe import AudioMetadata

logger = logging.getLogger("soundagent.renamer")


def build_filename(
    suggested: str,
    meta: AudioMetadata,
    original_path: Path,
) -> str:
    """
    Returns the full filename string (no directory component).
    e.g. WTHR_rain-woodland-wind-light_96k24b.wav
    """
    ext = original_path.suffix
    suffix = _technical_suffix(meta)
    parts = suggested.split("_", 1)
    cat_id = parts[0].upper()
    slug = _sanitise_slug(parts[1]) if len(parts) == 2 else ""
    if not slug:
        slug = _sanitise_slug(original_path.stem)
    stem = f"{cat_id}_{slug}{suffix}" if slug else f"{cat_id}{suffix}"
    return f"{stem}{ext}"


def _sanitise_slug(raw: str) -> str:
    """
    Lowercase, replace spaces/underscores with hyphens,
    strip non [a-z0-9-], collapse multiple hyphens,
    truncate to 60 chars. Returns empty string if nothing remains.
    """
    s = raw.lower()
    s = re.sub(r"[ _]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s[:60]


def _technical_suffix(meta: AudioMetadata) -> str:
    """
    Returns e.g. '_96k24b' or '_48k' (no bit_depth if None).
    """
    sr_k = round(meta.sample_rate / 1000)
    if meta.bit_depth is not None:
        return f"_{sr_k}k{meta.bit_depth}b"
    return f"_{sr_k}k"


def rename_staged_file(
    staged_path: Path,
    suggested: str | None,
    meta: AudioMetadata,
    dry_run: bool = False,
) -> Path:
    """
    Renames the file within its current directory (_staging/).
    Handles collisions by appending _2, _3 etc. before the extension.
    Returns the new Path (same directory, new name).
    On dry_run: logs the intended rename and returns the would-be Path
    without touching the filesystem.
    If suggested is None or empty, falls back to sanitised original stem
    + technical suffix and logs a warning.
    Never raises — on any error, returns staged_path unchanged and logs.
    """
    try:
        original_name = staged_path.name
        ext = staged_path.suffix
        suffix = _technical_suffix(meta)

        if not suggested:
            logger.warning(
                f"suggested_filename missing for {original_name} — using sanitised original stem"
            )
            slug = _sanitise_slug(staged_path.stem)
            base_stem = f"{slug}{suffix}" if slug else f"file{suffix}"
        else:
            new_full = build_filename(suggested, meta, staged_path)
            base_stem = Path(new_full).stem

        new_path = staged_path.parent / f"{base_stem}{ext}"

        # Resolve collisions (skip if path is unchanged)
        if new_path != staged_path:
            counter = 2
            while new_path.exists():
                new_path = staged_path.parent / f"{base_stem}_{counter}{ext}"
                counter += 1

        if dry_run:
            logger.info(f"[DRY-RUN] rename: {original_name} → {new_path.name}")
            return new_path

        if new_path != staged_path:
            staged_path.rename(new_path)
            logger.info(f"Renamed: {original_name} → {new_path.name}")

        return new_path

    except Exception as exc:
        logger.error(f"Rename failed for {staged_path.name}: {exc} — keeping original name")
        return staged_path
