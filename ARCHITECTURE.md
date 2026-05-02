# SoundAgent — Technical Architecture

Living reference. Updated as each phase is implemented. Documents what is **actually built**, not the plan.

---

## Module map

```
soundagent/
├── __main__.py        CLI entrypoint — argument parsing, config load, dispatch
├── config.py          Config dataclasses + YAML/env loader
├── logging_setup.py   Rotating file + console logging setup
├── init_library.py    Library folder hierarchy creator
├── ffprobe.py         ffprobe subprocess wrapper → AudioMetadata
├── tick.py            Tick runner — orchestrates full pipeline
├── dedup.py           SHA-256 file hasher
├── ingest.py          Extension allowlist validator + atomic stage_file()
├── ingest_log.py      JSONL ingest event writer
├── enrichment.py      Claude API client, prompt, response parser, JSON cache
├── ucs.py             EnrichmentResult → UCSFields mapper (CatID, FXName, etc.)
├── embed.py           Metadata embedding: iXML/BWF · ID3 · FLAC · AIFF · XMP sidecar
├── router.py          Routing rules engine + atomic deliver() + sidecar override
├── catalogue.py       SQLite catalogue: schema, upsert, FTS5 queries, cross-tick dedup
├── webdav_server.py   wsgidav server start/stop/status via subprocess + PID file
└── adapters/
    ├── __init__.py    get_adapter() factory
    ├── base.py        BaseAdapter ABC
    ├── local.py       LocalAdapter + NetworkAdapter (watchdog-style scan)
    ├── rclone.py      RcloneAdapter (rclone copy; mount not yet implemented)
    └── webdav.py      WebDAVAdapter (passive inbox scan; server managed separately)
```

---

## Config system

**File:** `soundagent/config.py`

Two-layer: YAML file is loaded first, then env vars overwrite specific keys.

```
config.yaml  →  load_config()  →  Config dataclass
                    ↑
              env var overrides applied before dataclass construction
```

**Env vars recognised:**

| Variable | Overrides |
|---|---|
| `SOUNDAGENT_LIBRARY_ROOT` | `library_root` |
| `SOUNDAGENT_BASEHEAD_IMPORT_PATH` | `basehead_import_path` |
| `ANTHROPIC_API_KEY` | `Config.anthropic_api_key` (also read by Anthropic SDK automatically) |
| `SOUNDAGENT_WEBDAV_PASSWORD` | read by WebDAV adapter (P2) — not yet in config loader |

**Data structures:**

```python
@dataclass
class SourceConfig:
    name: str
    type: str        # local | network | rclone | webdav
    enabled: bool
    options: dict    # all remaining YAML keys for that source (path, port, remote, etc.)

@dataclass
class Config:
    library_root: Path
    basehead_import_path: Path
    tick_interval: int           # seconds — Cowork uses this to schedule next tick
    log_level: str
    sources: list[SourceConfig]
    anthropic_api_key: str
    raw: dict                    # full parsed YAML, unmodified
```

`SourceConfig.options` holds all type-specific fields verbatim from YAML (e.g. `path` for local/network, `remote`/`remote_path`/`mode`/`interval` for rclone, `port`/`auth`/`username` for webdav). The adapter (P2) reads from `options` directly.

---

## CLI

**File:** `soundagent/__main__.py`  
**Invocation:** `python -m soundagent [--config PATH] <command>`

| Command | Flag | Effect |
|---|---|---|
| `init` | | Creates library folder hierarchy |
| `tick` | `--dry-run` | Runs one agent tick; exits 0 (clean) or 1 (partial failure) |
| `query` | `[TERM…]` `--category` `--subcategory` `--source` `--min-duration` `--max-duration` `--min-bpm` `--max-bpm` `--limit` `--json` | Search the SQLite catalogue |
| `webdav start\|stop\|status` | | WebDAV server lifecycle |

Config is loaded and logging is set up before dispatch to any command. Config errors exit with code 2.

---

## Logging

**File:** `soundagent/logging_setup.py`

Always attaches a console `StreamHandler`. Attaches a `RotatingFileHandler` (5 MB × 5 files → `<library_root>/soundagent.log`) **only if `library_root` already exists** — this avoids a crash when `init` hasn't been run yet. Logger names follow the `soundagent.<module>` hierarchy (e.g. `soundagent.tick`, `soundagent.init`).

---

## Library folder hierarchy

**File:** `soundagent/init_library.py`

`init_library(cfg)` creates all dirs in `SUBDIRS` under `cfg.library_root` using `mkdir(parents=True, exist_ok=True)` — idempotent. With `dry_run=True` it logs intended paths and touches nothing.

```
<library_root>/
├── _inbox/            all adapters deliver here
├── _staging/          atomic copy target during processing
├── _errors/           quarantined files (bad format, hash failure) with source annotation
├── unclassified/      low-confidence enrichment fallback (P3)
├── archive/
├── field/{nature,urban,industrial,interior}/
├── sfx/{impacts,ambience,foley,designed}/
├── music/{loops,stems,beds,stingers}/
├── broadcast/{idents,vo,transitions}/
├── soundagent.log     rotating log (created after first tick)
└── summary.json       last tick's structured report
```

`basehead_import_path` is configured separately — it's where the agent delivers finished files for Basehead to watch. It is not created by `init_library`; it must already exist or be configured in Basehead.

---

## ffprobe wrapper

**File:** `soundagent/ffprobe.py`

Calls `ffprobe -v quiet -print_format json -show_streams -show_format <path>` via `subprocess.run`. Picks the first stream with `codec_type == "audio"`.

```python
@dataclass
class AudioMetadata:
    duration_s: float
    sample_rate: int
    bit_depth: int | None    # None if ffprobe doesn't report it (e.g. MP3)
    channels: int
    format: str              # ffprobe format_name (e.g. "wav", "mp3", "aiff")
    codec: str               # codec_name (e.g. "pcm_s24le", "mp3")
    file_size: int           # bytes
```

`bit_depth` checks both `bits_per_sample` and `bits_per_raw_sample` — ffprobe reports these inconsistently across formats. Raises `RuntimeError` if ffprobe is missing from PATH; raises `ValueError` if no audio stream is found.

---

## Tick runner

**File:** `soundagent/tick.py`

`run_tick(cfg, dry_run) -> int` returns exit code 0 or 1. On completion (not dry-run, library exists) it writes `<library_root>/summary.json`:

```json
{
  "duration_s": 0.01,
  "dry_run": false,
  "sources": ["local-inbox"],
  "errors": []
}
```

**Pipeline steps and implementation status:**

| Step | Description | Status |
|---|---|---|
| Health check | Check each enabled source adapter | **Done (P2)** |
| Scan | Adapters deliver files to `_inbox/` | **Done (P2)** |
| Dedup | SHA-256 within-tick + `catalogue.is_known()` cross-tick | **Done (P6)** |
| Validate | Extension/format allowlist → `_errors/` | **Done (P2)** |
| Stage | Atomic copy to `_staging/` + ffprobe | **Done (P2)** |
| Enrich | Claude API → structured JSON | **Done (P3)** |
| Embed | iXML/BWF · ID3 · XMP sidecar | **Done (P4)** |
| Route | Rules engine → target path | **Done (P5)** |
| Deliver | Atomic move → basehead_import_path | **Done (P5)** |
| Catalogue | SQLite upsert + FTS5 index | **Done (P6)** |
| Report | summary.json + ingest.log (JSONL) | **Done (P2)** |

---

## Ingest adapters (P2)

All adapters share the `BaseAdapter` ABC (`adapters/base.py`). The `inbox` property always resolves to `cfg.library_root / "_inbox"` — adapters must not write elsewhere.

**`collect(dry_run) -> list[Path]`** is the only required method. It returns paths of files now in `_inbox/` ready for the pipeline.

| Adapter | `is_available()` | `collect()` behaviour |
|---|---|---|
| `LocalAdapter` | `source_path.exists()` | Scans `options["path"]`; if same as inbox, enumerates in place; otherwise atomic-copies (copy2 + rename) then returns inbox paths |
| `NetworkAdapter` | Same but wraps in `try/except OSError` | Skips with warning if unavailable |
| `RcloneAdapter` | `rclone lsd remote: --max-depth 0` (10s timeout) | Snapshots inbox before, runs `rclone copy remote:path inbox/`, returns newly added files |
| `WebDAVAdapter` | `webdav_server.is_running(cfg)` (PID file check) | Returns files already in inbox; does not start/stop server |

**WebDAV server lifecycle** (`webdav_server.py`):
- `start()` launches a detached subprocess running `soundagent webdav _serve`, writes PID to `<library_root>/webdav.pid`
- `stop()` reads PID, terminates via `taskkill /F` (Windows) or SIGTERM (Unix), removes PID file
- `serve()` is the internal blocking loop (wsgidav + wsgiref), called only by `_serve` subcommand
- Password read from `SOUNDAGENT_WEBDAV_PASSWORD` env var

**Ingest pipeline** (`tick.py` steps 1–5):
1. Each enabled source: `is_available()` → skip with warning if false
2. `collect()` → raw file list with source name
3. SHA-256 dedup within the tick (same hash seen twice → skip second; cross-tick dedup in P6)
4. Extension allowlist (`ingest.py:ALLOWED_EXTENSIONS`) → rejected files moved to `_errors/`
5. `stage_file()` → atomic copy to `_staging/`, collision-safe (appends 8-char hash fragment); `ffprobe.extract()` runs on staging path; src unlinked from inbox only after successful stage

Events written to `<library_root>/ingest.log` (JSONL, one record per file):
```json
{"timestamp": "...", "filename": "kick.wav", "hash": "abc...", "source": "local-inbox", "status": "staged", "duration_s": 2.1, "sample_rate": 48000, "codec": "pcm_s24le"}
```
Status values: `staged` | `rejected` | `error`

## Enrichment pipeline (P3)

**File:** `soundagent/enrichment.py`

`enrich(filename, file_hash, meta, cfg, cache) -> EnrichmentResult`

Flow: cache lookup → Claude API call → JSON parse → validate → cache write.

**Cache** (`EnrichmentCache`): JSON file at `<library_root>/enrichment_cache.json`, keyed by SHA-256. Loaded once per tick, written after each new result. P6 will migrate this into SQLite.

**API call** (`_call_api`): Uses `claude-sonnet-4-6` with prompt caching on the system prompt (`cache_control: ephemeral`). Retries on `RateLimitError`, `APIConnectionError`, `InternalServerError` — exponential backoff, 5 attempts max (tenacity).

**Response validation** (`_validate`): Enforces:
- `category` ∈ `{field, sfx, music, broadcast}`
- `subcategory` valid for that category (see `VALID_SUBCATEGORIES`)
- All required fields present
- `confidence` clamped to `[0.0, 1.0]`
- `low_confidence = confidence < 0.70` — tick.py logs these for `/unclassified/` routing (P5)

**EnrichmentResult fields:**

| Field | Type | Notes |
|---|---|---|
| `category` | str | field / sfx / music / broadcast |
| `subcategory` | str | one of the valid subs for the category |
| `description` | str | 1–2 sentence natural language description |
| `tags` | list[str] | lowercased |
| `mood` | str | free-form descriptor |
| `energy` | str | low / medium / high |
| `bpm` | float \| None | music only |
| `key` | str \| None | music only |
| `confidence` | float | 0.0–1.0 |
| `low_confidence` | bool | True when confidence < 0.70 |

## SQLite Catalogue (P6)

**File:** `soundagent/catalogue.py`  
**Database:** `<library_root>/soundlibrary.db` (WAL mode, FK enforcement)

`open_catalogue(library_root) -> Catalogue` is the entry point. Schema is applied idempotently via `executescript` on first connect.

**Schema:**

| Table | Key | Purpose |
|---|---|---|
| `files` | `hash TEXT PK` | One row per unique file — technical + routing metadata |
| `enrichment` | `hash FK` | Claude enrichment result for each file |
| `ingest_log` | `id AUTOINCREMENT` | Structured append-only event log |
| `fts_search` | FTS5 virtual | Content-indexed over `enrichment(description, tags)` |

FTS triggers keep `fts_search` in sync with `enrichment` on INSERT/UPDATE/DELETE.

**Key methods:**

| Method | Notes |
|---|---|
| `is_known(hash)` | `True` if file has been fully delivered (`library_path IS NOT NULL`) |
| `upsert_file(...)` | ON CONFLICT: updates `last_seen`, preserves existing `library_path` via COALESCE |
| `upsert_enrichment(...)` | Tags stored as JSON array; ON CONFLICT replaces all fields |
| `log_event(filename, hash, source, status, **detail)` | `detail` serialised as JSON blob |
| `search(query, category, …)` | FTS5 MATCH when `query` given; plain SQL filters otherwise |
| `integrity_check()` | Runs `PRAGMA integrity_check`; logs error and returns False on failure |

**Tick integration** (`tick.py`):
- `integrity_check()` runs at tick start; warning logged on failure (does not abort tick)
- `is_known(hash)` in dedup step replaces within-tick-only dedup — already-processed files are skipped immediately and logged as `skipped_known`
- After successful delivery: `upsert_file()` + `upsert_enrichment()` + `log_event("delivered")`

**CLI query command:**
```
python -m soundagent query [TERM…] [--category CAT] [--subcategory SUB]
    [--source ADAPTER] [--min-duration S] [--max-duration S]
    [--min-bpm BPM] [--max-bpm BPM] [--limit N] [--json]
```
Positional terms → FTS MATCH against description+tags. `--json` outputs raw JSON.

## Planned modules (not yet built)

| Module | Phase | Purpose |
|---|---|---|
| `soundagent/api.py` | P8 | FastAPI search server |

---

## Key constraints to remember

- **rclone mount on Windows** requires WinFsp (FUSE layer). Sync mode works without it.
- **WebDAV server** must start and stop cleanly with the agent process — lifecycle tied to tick in Cowork context.
- **Basehead iXML import fields** are undocumented. UCS field mapping (P4) must be validated empirically against a live Basehead instance before considering it done.
- **Non-ASCII filenames** in iXML have known edge cases — test with multilingual content in P4.
- **`_inbox/` is the only handoff point** between adapters and the rest of the pipeline. Adapters must not write anywhere else.
