import json
import logging
import time
from pathlib import Path

from soundagent.config import Config
from soundagent.ffprobe import AudioMetadata

log = logging.getLogger("soundagent.tick")


def run_tick(cfg: Config, dry_run: bool = False) -> int:
    """Run one agent tick. Returns exit code: 0=clean, 1=partial failure."""
    from soundagent.adapters import get_adapter
    from soundagent import ffprobe
    from soundagent.dedup import sha256
    from soundagent.ingest import is_allowed, stage_file
    from soundagent.ingest_log import IngestLog
    from soundagent.enrichment import EnrichmentCache, enrich

    start = time.monotonic()
    mode = " (dry-run)" if dry_run else ""
    log.info(f"--- TICK START{mode} ---")

    errors_dir = cfg.library_root / "_errors"
    staging_dir = cfg.library_root / "_staging"
    ingest_log = IngestLog(cfg.library_root / "ingest.log")
    cache = EnrichmentCache(cfg.library_root / "enrichment_cache.json")
    errors: list[str] = []

    # ── 1+2: adapter health check + scan ─────────────────────────────────────
    raw_files: list[tuple[Path, str]] = []
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
        _write_summary(cfg, start, dry_run, [], errors, active)
        return 0

    # ── 3: dedup (within-tick; catalogue dedup in P6) ────────────────────────
    seen_hashes: dict[str, str] = {}
    deduped: list[tuple[Path, str, str]] = []
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
    staged: list[tuple[Path, str, str, AudioMetadata]] = []  # (path, hash, adapter, meta)
    for f, h, adapter_name in valid:
        try:
            staging_path = stage_file(f, staging_dir, hash_fragment=h)
            meta = ffprobe.extract(staging_path)
            f.unlink(missing_ok=True)
            staged.append((staging_path, h, adapter_name, meta))
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

    # ── 6: enrich ────────────────────────────────────────────────────────────
    enriched: list[tuple[Path, str, str, AudioMetadata, object]] = []
    unclassified_dir = cfg.library_root / "unclassified"
    for staging_path, h, adapter_name, meta in staged:
        try:
            result = enrich(staging_path.name, h, meta, cfg, cache)
            enriched.append((staging_path, h, adapter_name, meta, result))
            ingest_log.write(
                staging_path.name, h, adapter_name, "enriched",
                category=result.category,
                subcategory=result.subcategory,
                confidence=result.confidence,
                low_confidence=result.low_confidence,
            )
        except Exception as exc:
            log.error(f"Enrichment failed for {staging_path.name}: {exc}")
            ingest_log.write(staging_path.name, h, adapter_name, "enrich_error", error=str(exc))
            errors.append(staging_path.name)

    # ── 7: embed metadata ────────────────────────────────────────────────────
    from soundagent.ucs import map_to_ucs
    from soundagent.embed import embed

    embedded: list[tuple] = []
    for staging_path, h, adapter_name, meta, result in enriched:
        try:
            ucs = map_to_ucs(result, staging_path.name)
            embed(staging_path, ucs)
            embedded.append((staging_path, h, adapter_name, meta, result, ucs))
            ingest_log.write(
                staging_path.name, h, adapter_name, "embedded",
                cat_id=ucs.cat_id,
            )
            log.info(f"Embedded: {staging_path.name} [{ucs.cat_id}]")
        except Exception as exc:
            log.error(f"Embed failed for {staging_path.name}: {exc}")
            ingest_log.write(staging_path.name, h, adapter_name, "embed_error", error=str(exc))
            errors.append(staging_path.name)

    # ── 8+9: route + deliver ─────────────────────────────────────────────────
    from soundagent.router import route, deliver

    delivered: list[dict] = []
    for staging_path, h, adapter_name, meta, result, ucs in embedded:
        try:
            decision = route(staging_path, result, cfg)
            final_path = deliver(staging_path, decision, h, dry_run=False)
            ingest_log.write(
                final_path.name, h, adapter_name, "delivered",
                destination=str(final_path),
                unclassified=decision.is_unclassified,
                override=decision.override_used,
            )
            delivered.append({
                "filename": final_path.name,
                "hash": h,
                "source": adapter_name,
                "category": result.category,
                "subcategory": result.subcategory,
                "cat_id": ucs.cat_id,
                "confidence": result.confidence,
                "low_confidence": result.low_confidence,
                "destination": str(final_path),
            })
        except Exception as exc:
            log.error(f"Routing/delivery failed for {staging_path.name}: {exc}")
            ingest_log.write(staging_path.name, h, adapter_name, "route_error", error=str(exc))
            errors.append(staging_path.name)

    # ── P6: catalogue (not yet implemented) ───────────────────────────────────
    if delivered:
        log.info(f"{len(delivered)} file(s) delivered — catalogue not yet implemented (Phase 6)")

    summary_records = delivered
    _write_summary(cfg, start, dry_run, summary_records, errors, active)

    exit_code = 1 if errors else 0
    elapsed = time.monotonic() - start
    log.info(f"--- TICK END ({elapsed:.1f}s, exit={exit_code}) ---")
    return exit_code


def _write_summary(cfg: Config, start: float, dry_run: bool, staged: list, errors: list, active: list) -> None:
    import time as _t
    summary = {
        "duration_s": round(_t.monotonic() - start, 2),
        "dry_run": dry_run,
        "sources": [s.name for s in active],
        "staged": len(staged),
        "errors": errors,
    }
    if not dry_run and cfg.library_root.exists():
        (cfg.library_root / "summary.json").write_text(json.dumps(summary, indent=2))
