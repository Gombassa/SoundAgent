import json
import logging
import time
from pathlib import Path

from soundagent.config import Config

log = logging.getLogger("soundagent.tick")


def run_tick(cfg: Config, dry_run: bool = False) -> int:
    """Run one agent tick. Returns exit code: 0=clean, 1=partial failure."""
    from soundagent.adapters import get_adapter
    from soundagent import ffprobe
    from soundagent.dedup import sha256
    from soundagent.ingest import is_allowed, stage_file
    from soundagent.ingest_log import IngestLog

    start = time.monotonic()
    mode = " (dry-run)" if dry_run else ""
    log.info(f"--- TICK START{mode} ---")

    errors_dir = cfg.library_root / "_errors"
    staging_dir = cfg.library_root / "_staging"
    ingest_log = IngestLog(cfg.library_root / "ingest.log")
    errors: list[str] = []
    staged: list[dict] = []

    # ── 1+2: adapter health check + scan ─────────────────────────────────────
    raw_files: list[tuple[Path, str]] = []   # (inbox path, adapter name)
    active = [s for s in cfg.sources if s.enabled]
    for source in active:
        adapter = get_adapter(cfg, source)
        if not adapter.is_available():
            log.warning(f"[{source.name}] unavailable, skipping this tick")
            continue
        collected = adapter.collect(dry_run=dry_run)
        for f in collected:
            raw_files.append((f, source.name))
        log.info(f"[{source.name}] {len(collected)} file(s) collected")

    if dry_run:
        log.info(f"[dry-run] {len(raw_files)} file(s) would be processed")
        _write_summary(cfg, start, dry_run, staged, errors, active)
        return 0

    # ── 3: dedup (within-tick hash check; catalogue dedup in P6) ─────────────
    seen_hashes: dict[str, str] = {}   # hash → filename
    deduped: list[tuple[Path, str, str]] = []   # (path, hash, adapter)
    for f, adapter_name in raw_files:
        h = sha256(f)
        if h in seen_hashes:
            log.info(f"Duplicate of {seen_hashes[h]!r}, skipping {f.name}")
            continue
        seen_hashes[h] = f.name
        deduped.append((f, h, adapter_name))

    # ── 4: format validation ──────────────────────────────────────────────────
    valid: list[tuple[Path, str, str]] = []
    errors_dir.mkdir(parents=True, exist_ok=True)
    for f, h, adapter_name in deduped:
        if is_allowed(f):
            valid.append((f, h, adapter_name))
        else:
            dest = errors_dir / f.name
            f.rename(dest)
            log.warning(f"Rejected (unsupported format): {f.name}")
            ingest_log.write(f.name, h, adapter_name, "rejected")
            errors.append(f.name)

    # ── 5: stage + ffprobe ───────────────────────────────────────────────────
    for f, h, adapter_name in valid:
        try:
            staging_path = stage_file(f, staging_dir, hash_fragment=h)
            meta = ffprobe.extract(staging_path)
            f.unlink(missing_ok=True)   # remove from inbox after successful stage
            record = {
                "path": str(staging_path),
                "hash": h,
                "source": adapter_name,
                "duration_s": meta.duration_s,
                "sample_rate": meta.sample_rate,
                "bit_depth": meta.bit_depth,
                "channels": meta.channels,
                "format": meta.format,
                "codec": meta.codec,
            }
            staged.append(record)
            ingest_log.write(
                f.name, h, adapter_name, "staged",
                duration_s=meta.duration_s,
                sample_rate=meta.sample_rate,
                codec=meta.codec,
            )
            log.info(f"Staged: {f.name} [{meta.codec} {meta.sample_rate}Hz {meta.duration_s:.1f}s]")
        except Exception as exc:
            log.error(f"Failed to stage {f.name}: {exc}")
            ingest_log.write(f.name, h, adapter_name, "error", error=str(exc))
            errors.append(f.name)

    # ── P3: enrich (not yet implemented) ─────────────────────────────────────
    if staged:
        log.info(f"{len(staged)} file(s) staged — enrichment not yet implemented (Phase 3)")

    _write_summary(cfg, start, dry_run, staged, errors, active)
    exit_code = 1 if errors else 0
    elapsed = time.monotonic() - start
    log.info(f"--- TICK END ({elapsed:.1f}s, exit={exit_code}) ---")
    return exit_code


def _write_summary(cfg: Config, start: float, dry_run: bool, staged: list, errors: list, active: list) -> None:
    import time as _time
    summary = {
        "duration_s": round(_time.monotonic() - start, 2),
        "dry_run": dry_run,
        "sources": [s.name for s in active],
        "staged": len(staged),
        "errors": errors,
    }
    if not dry_run and cfg.library_root.exists():
        (cfg.library_root / "summary.json").write_text(json.dumps(summary, indent=2))
