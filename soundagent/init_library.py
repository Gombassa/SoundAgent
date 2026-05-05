import logging
from pathlib import Path

from soundagent.config import Config

log = logging.getLogger("soundagent.init")

SUBDIRS = [
    "_inbox",
    "_staging",
    "_errors",
    "_duplicates",
    "unclassified",
    "archive",
    "field/nature",
    "field/urban",
    "field/industrial",
    "field/interior",
    "sfx/impacts",
    "sfx/ambience",
    "sfx/foley",
    "sfx/designed",
    "music/loops",
    "music/stems",
    "music/beds",
    "music/stingers",
    "broadcast/idents",
    "broadcast/vo",
    "broadcast/transitions",
]


def init_library(cfg: Config, dry_run: bool = False) -> None:
    root = cfg.library_root
    created = 0
    for subdir in SUBDIRS:
        p = root / subdir
        if not p.exists():
            if dry_run:
                log.info(f"[dry-run] would create {p}")
            else:
                p.mkdir(parents=True, exist_ok=True)
                log.info(f"Created {p}")
                created += 1
        else:
            log.debug(f"Exists: {p}")

    if not dry_run:
        log.info(f"Library initialised at {root} ({created} dirs created)")
