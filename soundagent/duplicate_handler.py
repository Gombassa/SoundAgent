"""
soundagent/duplicate_handler.py

Moves duplicate files to _duplicates/ and writes a JSON sidecar.
"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("soundagent.duplicate_handler")


def quarantine(
    file_path: Path,
    duplicates_dir: Path,
    match_type: str,           # "exact_hash" | "fingerprint_match"
    matched_hash: str,         # SHA-256 of the existing file this matches
    matched_path: str,         # library path of the existing file
    matched_filename: str,     # delivered filename of the existing file
    similarity: float = 1.0,   # 1.0 for exact hash, 0.0–1.0 for fingerprint
    dry_run: bool = False,
) -> Path:
    """
    Moves file_path into duplicates_dir.
    Writes a JSON sidecar alongside it: {filename}.duplicate.json
    Returns the Path of the held file in _duplicates/.
    On dry_run: logs intended action, returns would-be Path, no filesystem writes.
    Never raises — on error logs and returns file_path unchanged.
    """
    dest = duplicates_dir / file_path.name
    sim_str = f" {similarity:.2f}" if match_type == "fingerprint_match" else ""

    if dry_run:
        logger.info(
            f"[DRY-RUN] duplicate ({match_type}{sim_str}): "
            f"{file_path.name} → _duplicates/ (matches {matched_filename})"
        )
        return dest

    try:
        duplicates_dir.mkdir(parents=True, exist_ok=True)

        # Collision-safe dest name
        if dest.exists():
            stem, ext = dest.stem, dest.suffix
            counter = 2
            while dest.exists():
                dest = duplicates_dir / f"{stem}_{counter}{ext}"
                counter += 1

        tmp = dest.parent / f".{dest.name}.tmp"
        shutil.copy2(str(file_path), tmp)
        tmp.replace(dest)
        file_path.unlink(missing_ok=True)

        sidecar = {
            "original_filename": file_path.name,
            "match_type": match_type,
            "matched_hash": matched_hash,
            "matched_path": matched_path,
            "matched_filename": matched_filename,
            "similarity": similarity,
            "detected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resolved": False,
        }
        sidecar_path = dest.with_suffix(dest.suffix + ".duplicate.json")
        sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

        logger.info(
            f"Quarantined duplicate ({match_type}{sim_str}): "
            f"{file_path.name} → _duplicates/ (matches {matched_filename})"
        )
        return dest

    except Exception as exc:
        logger.error(f"Failed to quarantine {file_path.name}: {exc}")
        return file_path
