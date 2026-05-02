import json
import logging
import time

from soundagent.config import Config

log = logging.getLogger("soundagent.tick")


def run_tick(cfg: Config, dry_run: bool = False) -> int:
    """Run one agent tick. Returns exit code: 0=clean, 1=partial failure."""
    start = time.monotonic()
    mode = " (dry-run)" if dry_run else ""
    log.info(f"--- TICK START{mode} ---")

    errors: list[str] = []

    # P2: adapter health checks + scan
    active = [s for s in cfg.sources if s.enabled]
    log.info(f"{len(active)} source(s) configured — ingest adapters not yet implemented (Phase 2)")

    elapsed = time.monotonic() - start
    summary = {
        "duration_s": round(elapsed, 2),
        "dry_run": dry_run,
        "sources": [s.name for s in active],
        "errors": errors,
    }

    if not dry_run and cfg.library_root.exists():
        summary_path = cfg.library_root / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))

    exit_code = 1 if errors else 0
    log.info(f"--- TICK END ({elapsed:.1f}s, exit={exit_code}) ---")
    return exit_code
