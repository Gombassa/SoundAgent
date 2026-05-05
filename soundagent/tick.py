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
    from soundagent.ingest import is_allowed, is_sidecar, stage_file
    from soundagent.ingest_log import IngestLog
    from soundagent.enrichment import EnrichmentCache, enrich
    from soundagent.catalogue import open_catalogue

    start = time.monotonic()
    mode = " (dry-run)" if dry_run else ""
    log.info(f"--- TICK START{mode} ---")

    errors_dir = cfg.library_root / "_errors"
    staging_dir = cfg.library_root / "_staging"
    duplicates_dir = cfg.library_root / "_duplicates"
    ingest_log = IngestLog(cfg.library_root / "ingest.log")
    cache = EnrichmentCache(
        cfg.library_root / "enrichment_cache.json",
        run_on_existing=cfg.audio_analysis.get("run_on_existing", False),
    )
    catalogue = open_catalogue(cfg.library_root)
    errors: list[str] = []
    dup_counts: dict[str, int] = {"exact_hash": 0, "fingerprint_match": 0}

    dup_cfg = cfg.duplicate_detection
    dup_enabled = dup_cfg.get("enabled", True)
    fpcalc_path = dup_cfg.get("fpcalc_path", "fpcalc")
    fp_threshold = float(dup_cfg.get("fingerprint_similarity_threshold", 0.85))

    if not catalogue.integrity_check():
        log.warning("Catalogue integrity check failed — proceeding cautiously")

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
        _write_summary(cfg, start, dry_run, [], errors, active, dup_counts)
        return 0

    # ── 3: dedup (within-tick + cross-tick via catalogue) ────────────────────
    from soundagent.duplicate_handler import quarantine as quarantine_duplicate

    duplicates_dir.mkdir(parents=True, exist_ok=True)

    # Same-name files from recursive scan land at the same inbox path; keep first only.
    seen_paths: set[Path] = set()
    unique_raw: list[tuple[Path, str]] = []
    for f, adapter_name in raw_files:
        if f not in seen_paths:
            seen_paths.add(f)
            unique_raw.append((f, adapter_name))
    raw_files = unique_raw

    # Discard DAW sidecar files (peak caches, session files) before dedup.
    # Inbox copies are deleted; files that are already in inbox (same-dir source) are skipped in place.
    inbox_dir = cfg.library_root / "_inbox"
    filtered_raw: list[tuple[Path, str]] = []
    for f, adapter_name in raw_files:
        if is_sidecar(f):
            if f.exists() and f.resolve().parent == inbox_dir.resolve():
                f.unlink()
            log.debug(f"Discarded sidecar: {f.name}")
        else:
            filtered_raw.append((f, adapter_name))
    raw_files = filtered_raw

    seen_hashes: dict[str, str] = {}
    deduped: list[tuple[Path, str, str]] = []
    for f, adapter_name in raw_files:
        if not f.exists():
            log.warning(f"Inbox file disappeared before processing, skipping: {f.name}")
            continue
        h = sha256(f)
        if h in seen_hashes:
            log.info(f"Within-tick duplicate of {seen_hashes[h]!r}, skipping {f.name}")
            continue
        if catalogue.is_known(h):
            existing = catalogue.get_file_by_hash(h)
            matched_path = existing["library_path"] if existing else ""
            matched_filename = existing["filename"] if existing else ""
            held = quarantine_duplicate(
                file_path=f,
                duplicates_dir=duplicates_dir,
                match_type="exact_hash",
                matched_hash=h,
                matched_path=matched_path or "",
                matched_filename=matched_filename or "",
                similarity=1.0,
                dry_run=dry_run,
            )
            catalogue.log_duplicate(
                filename=f.name,
                held_path=str(held),
                match_type="exact_hash",
                matched_hash=h,
                matched_path=matched_path,
                matched_filename=matched_filename,
                similarity=1.0,
            )
            ingest_log.write(f.name, h, adapter_name, "duplicate_exact")
            dup_counts["exact_hash"] += 1
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
            f.replace(dest)
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

    # ── 5a: fingerprint + near-duplicate check ───────────────────────────────
    from soundagent.fingerprinter import generate as fingerprint_file
    from soundagent.fingerprinter import is_available as fpcalc_is_available

    fp_results: dict[str, dict | None] = {}  # hash → fp_result
    fingerprinted: list[tuple[Path, str, str, AudioMetadata]] = []

    if dup_enabled:
        if not fpcalc_is_available(fpcalc_path):
            log.warning(
                "fpcalc not found — fingerprint matching disabled for this tick. "
                "Install from https://acoustid.org/chromaprint or set fpcalc_path in config."
            )
            fingerprinted = staged
        else:
            for staging_path, h, adapter_name, meta in staged:
                fp = fingerprint_file(staging_path, fpcalc_path=fpcalc_path)
                fp_results[h] = fp
                if fp:
                    match = catalogue.find_fingerprint_match(fp["fingerprint"], threshold=fp_threshold)
                    if match:
                        held = quarantine_duplicate(
                            file_path=staging_path,
                            duplicates_dir=duplicates_dir,
                            match_type="fingerprint_match",
                            matched_hash=match["hash"],
                            matched_path=match["path"] or "",
                            matched_filename=match["filename"] or "",
                            similarity=match["similarity"],
                            dry_run=dry_run,
                        )
                        catalogue.log_duplicate(
                            filename=staging_path.name,
                            held_path=str(held),
                            match_type="fingerprint_match",
                            matched_hash=match["hash"],
                            matched_path=match["path"],
                            matched_filename=match["filename"],
                            similarity=match["similarity"],
                        )
                        ingest_log.write(staging_path.name, h, adapter_name, "duplicate_fingerprint")
                        dup_counts["fingerprint_match"] += 1
                        continue
                fingerprinted.append((staging_path, h, adapter_name, meta))
    else:
        fingerprinted = staged

    # ── 6: audio analysis ────────────────────────────────────────────────────
    from soundagent.audio_analysis.pipeline import analyse as audio_analyse

    analysed: list[tuple[Path, str, str, AudioMetadata, object]] = []
    for staging_path, h, adapter_name, meta in fingerprinted:
        try:
            audio_result = audio_analyse(
                str(staging_path), h, cfg.audio_analysis,
                duration_s=meta.duration_s,
                anthropic_api_key=cfg.anthropic_api_key,
            )
            analysed.append((staging_path, h, adapter_name, meta, audio_result))
            log.info(
                f"Audio analysis: {staging_path.name} "
                f"[{audio_result.content_type}, models={audio_result.models_run}]"
            )
        except Exception as exc:
            log.error(f"Audio analysis failed for {staging_path.name}: {exc}")
            # Fall back to filename-only enrichment rather than dropping the file
            from soundagent.audio_analysis.result import AnalysisResult
            analysed.append((staging_path, h, adapter_name, meta, AnalysisResult.fallback(h)))

    # ── 7: enrich ────────────────────────────────────────────────────────────
    enriched: list[tuple[Path, str, str, AudioMetadata, object, object]] = []
    for staging_path, h, adapter_name, meta, audio_result in analysed:
        try:
            result = enrich(staging_path.name, h, meta, audio_result, cfg, cache)
            enriched.append((staging_path, h, adapter_name, meta, result, audio_result))
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

    # ── 7a: rename ───────────────────────────────────────────────────────────
    from soundagent.renamer import rename_staged_file

    renamed: list[tuple] = []
    for staging_path, h, adapter_name, meta, result, audio_result in enriched:
        staging_path = rename_staged_file(
            staged_path=staging_path,
            suggested=result.suggested_filename,
            meta=meta,
            dry_run=dry_run,
        )
        renamed.append((staging_path, h, adapter_name, meta, result, audio_result))

    # ── 8: embed metadata ────────────────────────────────────────────────────
    from soundagent.ucs import map_to_ucs
    from soundagent.embed import embed

    embedded: list[tuple] = []
    for staging_path, h, adapter_name, meta, result, audio_result in renamed:
        try:
            ucs = map_to_ucs(result, staging_path.name)
            embed(staging_path, ucs, original_filename=result.original_filename or None)
            embedded.append((staging_path, h, adapter_name, meta, result, audio_result, ucs))
            ingest_log.write(
                staging_path.name, h, adapter_name, "embedded",
                cat_id=ucs.cat_id,
            )
            log.info(f"Embedded: {staging_path.name} [{ucs.cat_id}]")
        except Exception as exc:
            log.error(f"Embed failed for {staging_path.name}: {exc}")
            ingest_log.write(staging_path.name, h, adapter_name, "embed_error", error=str(exc))
            errors.append(staging_path.name)

    # ── 9+10: route + deliver ─────────────────────────────────────────────────
    from soundagent.router import route, deliver

    delivered: list[dict] = []
    for staging_path, h, adapter_name, meta, result, audio_result, ucs in embedded:
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
                # meta fields for catalogue
                "format": meta.format,
                "codec": meta.codec,
                "duration_s": meta.duration_s,
                "sample_rate": meta.sample_rate,
                "bit_depth": meta.bit_depth,
                "channels": meta.channels,
                "file_size": meta.file_size,
                # enrichment fields for catalogue
                "description": result.description,
                "tags": result.tags,
                "mood": result.mood,
                "energy": result.energy,
                "bpm": result.bpm,
                "key": result.key,
                "content_type": result.content_type,
                "usage_suggestions": result.usage_suggestions,
                "notes": result.notes,
                "language": result.language,
                "original_filename": result.original_filename or None,
                # audio analysis fields for catalogue
                "yamnet_classes": audio_result.yamnet_classes,
                "audioclip_matches": audio_result.audioclip_matches,
                "audioclip_raw_scores": audio_result.audioclip_raw_scores,
                "whisper_summary": audio_result.whisper_summary,
                "whisper_language": audio_result.whisper_language,
                "essentia_bpm": audio_result.essentia_bpm,
                "essentia_key": audio_result.essentia_key,
                "essentia_mood": audio_result.essentia_mood,
                "essentia_genre": audio_result.essentia_genre,
                "models_run": audio_result.models_run,
                "models_failed": audio_result.models_failed,
                "analysis_duration_s": audio_result.analysis_duration_s,
            })
        except Exception as exc:
            log.error(f"Routing/delivery failed for {staging_path.name}: {exc}")
            ingest_log.write(staging_path.name, h, adapter_name, "route_error", error=str(exc))
            errors.append(staging_path.name)

    # ── 11: catalogue upsert ─────────────────────────────────────────────────
    for rec in delivered:
        try:
            catalogue.upsert_file(
                hash=rec["hash"],
                filename=rec["filename"],
                source_adapter=rec["source"],
                library_path=rec["destination"],
                format=rec.get("format", ""),
                codec=rec.get("codec", ""),
                duration_s=rec.get("duration_s", 0.0),
                sample_rate=rec.get("sample_rate", 0),
                bit_depth=rec.get("bit_depth"),
                channels=rec.get("channels", 0),
                file_size=rec.get("file_size", 0),
                original_filename=rec.get("original_filename"),
            )
            catalogue.upsert_enrichment(
                hash=rec["hash"],
                category=rec["category"],
                subcategory=rec["subcategory"],
                cat_id=rec["cat_id"],
                description=rec.get("description", ""),
                tags=rec.get("tags", []),
                mood=rec.get("mood", ""),
                energy=rec.get("energy", ""),
                bpm=rec.get("bpm"),
                key=rec.get("key"),
                confidence=rec["confidence"],
                low_confidence=rec["low_confidence"],
                content_type=rec.get("content_type"),
                usage_suggestions=rec.get("usage_suggestions"),
                notes=rec.get("notes"),
                language=rec.get("language"),
                yamnet_classes=rec.get("yamnet_classes"),
                audioclip_matches=rec.get("audioclip_matches"),
                audioclip_raw_scores=rec.get("audioclip_raw_scores"),
                whisper_summary=rec.get("whisper_summary"),
                whisper_language=rec.get("whisper_language"),
                essentia_bpm=rec.get("essentia_bpm"),
                essentia_key=rec.get("essentia_key"),
                essentia_mood=rec.get("essentia_mood"),
                essentia_genre=rec.get("essentia_genre"),
                models_run=rec.get("models_run"),
                models_failed=rec.get("models_failed"),
            )
            catalogue.log_event(
                rec["filename"], rec["hash"], rec["source"], "delivered",
                destination=rec["destination"],
                cat_id=rec["cat_id"],
            )
            fp = fp_results.get(rec["hash"])
            if fp:
                catalogue.store_fingerprint(
                    hash=rec["hash"],
                    fingerprint=fp["fingerprint"],
                    duration_s=fp.get("duration"),
                    fpcalc_ver=None,
                )
        except Exception as exc:
            log.error(f"Catalogue upsert failed for {rec['filename']}: {exc}")

    catalogue.close()

    summary_records = delivered
    _write_summary(cfg, start, dry_run, summary_records, errors, active, dup_counts)

    exit_code = 1 if errors else 0
    elapsed = time.monotonic() - start
    log.info(f"--- TICK END ({elapsed:.1f}s, exit={exit_code}) ---")
    return exit_code


def _write_summary(
    cfg: Config, start: float, dry_run: bool, staged: list,
    errors: list, active: list, dup_counts: dict,
) -> None:
    import time as _t
    elapsed = round(_t.monotonic() - start, 2)
    summary = {
        "duration_s": elapsed,
        "dry_run": dry_run,
        "sources": [s.name for s in active],
        "staged": len(staged),
        "errors": errors,
        "duplicates": {
            "exact_hash": dup_counts.get("exact_hash", 0),
            "fingerprint_match": dup_counts.get("fingerprint_match", 0),
            "total": sum(dup_counts.values()),
        },
    }
    if not dry_run and cfg.library_root.exists():
        (cfg.library_root / "summary.json").write_text(json.dumps(summary, indent=2))

    # Print a clean stdout report for Cowork / log capture
    mode = " [DRY RUN]" if dry_run else ""
    print(f"\n=== SoundAgent Tick Report{mode} ===")
    print(f"Duration : {elapsed}s")
    print(f"Sources  : {', '.join(s.name for s in active) or 'none'}")
    print(f"Delivered: {len(staged)} file(s)")
    total_dups = sum(dup_counts.values())
    if total_dups:
        print(f"Dupes    : {total_dups} held "
              f"({dup_counts['exact_hash']} exact, {dup_counts['fingerprint_match']} fingerprint)")
    if errors:
        print(f"Errors   : {len(errors)} file(s)")
        for e in errors:
            print(f"  - {e}")
    else:
        print("Errors   : none")

    if not dry_run and staged:
        print("\nDelivered files:")
        for rec in staged:
            cat = rec.get("cat_id") or rec.get("category", "?")
            conf = rec.get("confidence", 0)
            flag = " [LOW CONFIDENCE]" if rec.get("low_confidence") else ""
            print(f"  {rec['filename']}  [{cat}]  confidence={conf:.2f}{flag}")
    print("=================================\n")
