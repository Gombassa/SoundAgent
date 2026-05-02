"""
Routing rules engine + delivery.

Determines where each staged file goes in the library and delivers it
to the Basehead import folder.

Routing priority:
  1. Per-file sidecar override (<filename>.soundagent.json)
  2. Low-confidence → unclassified/
  3. category/subcategory → matching library subfolder
"""

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from soundagent.config import Config
from soundagent.enrichment import EnrichmentResult

log = logging.getLogger("soundagent.router")


@dataclass
class RoutingDecision:
    library_dest: Path      # final resting place in the organised library
    basehead_dest: Path     # copy placed in Basehead import/watch folder
    is_unclassified: bool
    override_used: bool


def route(
    staging_path: Path,
    result: EnrichmentResult,
    cfg: Config,
) -> RoutingDecision:
    """Determine library destination for staging_path based on enrichment result."""
    override = _read_sidecar(staging_path)

    if override:
        dest_dir = cfg.library_root / override.strip("/")
        is_unclassified = False
        override_used = True
        log.debug(f"[{staging_path.name}] sidecar override → {override}")
    elif result.low_confidence:
        dest_dir = cfg.library_root / "unclassified"
        is_unclassified = True
        override_used = False
        log.debug(f"[{staging_path.name}] low confidence ({result.confidence:.2f}) → unclassified/")
    else:
        dest_dir = cfg.library_root / result.category / result.subcategory
        is_unclassified = False
        override_used = False

    dest_dir.mkdir(parents=True, exist_ok=True)

    return RoutingDecision(
        library_dest=dest_dir / staging_path.name,
        basehead_dest=cfg.basehead_import_path / staging_path.name,
        is_unclassified=is_unclassified,
        override_used=override_used,
    )


def deliver(
    staging_path: Path,
    decision: RoutingDecision,
    file_hash: str,
    dry_run: bool = False,
) -> Path:
    """Atomically move file to library destination; copy to Basehead import folder.

    Returns the final library path.
    """
    lib_dest = _resolve_collision(decision.library_dest, file_hash)
    bh_dest  = _resolve_collision(decision.basehead_dest, file_hash)

    if dry_run:
        log.info(f"[dry-run] {staging_path.name} → {lib_dest.relative_to(lib_dest.parents[1])}")
        return lib_dest

    # Atomic move to library (copy + rename so a crash mid-write leaves source intact)
    tmp = lib_dest.parent / f".{lib_dest.name}.tmp"
    shutil.copy2(staging_path, tmp)
    tmp.rename(lib_dest)
    staging_path.unlink(missing_ok=True)

    # Copy to Basehead import folder so Basehead picks it up on its next scan
    bh_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(lib_dest, bh_dest)

    try:
        rel = lib_dest.relative_to(lib_dest.parents[1])
    except ValueError:
        rel = lib_dest
    log.info(f"Delivered: {lib_dest.name} → {rel}")
    return lib_dest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_collision(path: Path, file_hash: str = "") -> Path:
    if not path.exists():
        return path
    fragment = file_hash[:8] if file_hash else "dup"
    return path.parent / f"{path.stem}_{fragment}{path.suffix}"


def _read_sidecar(path: Path) -> Optional[str]:
    """Return destination override from <filename>.soundagent.json, or None."""
    sidecar = path.with_suffix(path.suffix + ".soundagent.json")
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        dest = str(data.get("destination", "")).strip()
        return dest or None
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not read sidecar {sidecar.name}: {e}")
        return None
