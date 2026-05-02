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
├── enrichment.py      Claude API client, prompt builder, response parser, JSON cache
├── ucs.py             EnrichmentResult → UCSFields mapper (CatID, FXName, etc.)
├── embed.py           Metadata embedding: iXML/BWF · ID3 · FLAC · AIFF · XMP sidecar
├── router.py          Routing rules engine + atomic deliver() + sidecar override
├── catalogue.py       SQLite catalogue: schema, migration, upsert, FTS5, cross-tick dedup
├── webdav_server.py   wsgidav server start/stop/status via subprocess + PID file
├── audio_analysis/    ← NEW: ML audio analysis pipeline
│   ├── __init__.py    Exports AnalysisResult
│   ├── result.py      AnalysisResult dataclass + fallback() factory
│   ├── preprocessor.py  ffmpeg audio conversion (16kHz + 44kHz), waveform loading
│   ├── yamnet_analyzer.py  YAMNet (TF Hub): sound events + content-type routing
│   ├── whisper_analyzer.py Whisper: transcription + language detection
│   ├── audioclip_analyzer.py AudioCLIP: zero-shot semantic tagging
│   ├── essentia_analyzer.py  Essentia: BPM, key, mood, genre (music only)
│   └── pipeline.py    Orchestrator: runs all models, fallback path, AnalysisResult
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
    audio_analysis: dict         # ← NEW: all audio_analysis.* YAML keys as a plain dict
    raw: dict                    # full parsed YAML, unmodified
```

`Config.audio_analysis` is populated from `raw.get("audio_analysis", {})`. Keys: `enabled`, `audioclip_weights_path`, `whisper_model_size`, `yamnet_cache_dir`, `yamnet_top_n`, `yamnet_min_score`, `audioclip_min_score`, `audioclip_prompts`, `speech_threshold`, `music_threshold`, `max_analysis_duration_s`, `run_on_existing`.

---

## CLI

**File:** `soundagent/__main__.py`  
**Invocation:** `python -m soundagent [--config PATH] <command>`

| Command | Flags | Effect |
|---|---|---|
| `init` | | Creates library folder hierarchy |
| `tick` | `--dry-run` | Runs one agent tick; exits 0 (clean) or 1 (partial failure) |
| `query` | `[TERM…]` `--category` `--subcategory` `--source` `--content-type` `--language` `--min-duration` `--max-duration` `--min-bpm` `--max-bpm` `--confidence-min` `--limit` `--json` | Search the SQLite catalogue |
| `webdav start\|stop\|status` | | WebDAV server lifecycle |

Config is loaded and logging is set up before dispatch to any command. Config errors exit with code 2.

---

## Logging

**File:** `soundagent/logging_setup.py`

Always attaches a console `StreamHandler`. Attaches a `RotatingFileHandler` (5 MB × 5 files → `<library_root>/soundagent.log`) **only if `library_root` already exists** — this avoids a crash when `init` hasn't been run yet. Logger names follow the `soundagent.<module>` hierarchy (e.g. `soundagent.tick`, `soundagent.audio_analysis.pipeline`).

---

## Library folder hierarchy

**File:** `soundagent/init_library.py`

`init_library(cfg)` creates all dirs in `SUBDIRS` under `cfg.library_root` using `mkdir(parents=True, exist_ok=True)` — idempotent. With `dry_run=True` it logs intended paths and touches nothing.

```
<library_root>/
├── _inbox/            all adapters deliver here
├── _staging/          atomic copy target during processing
├── _errors/           quarantined files (bad format, hash failure) with source annotation
├── unclassified/      low-confidence enrichment fallback
├── archive/
├── field/{nature,urban,industrial,interior}/
├── sfx/{impacts,ambience,foley,designed}/
├── music/{loops,stems,beds,stingers}/
├── broadcast/{idents,vo,transitions}/
├── soundagent.log     rotating log (created after first tick)
└── summary.json       last tick's structured report
```

New categories from the audio analysis enrichment prompt (`voice/`, `ambience/`) are created automatically by `router.py`'s `mkdir(parents=True, exist_ok=True)` call — no change to `init_library.py` needed.

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

`run_tick(cfg, dry_run) -> int` returns exit code 0 or 1. On completion (not dry-run, library exists) it writes `<library_root>/summary.json`.

**Pipeline steps and implementation status:**

| Step | Description | Status |
|---|---|---|
| Health check | Check each enabled source adapter | **Done (P2)** |
| Scan | Adapters deliver files to `_inbox/` | **Done (P2)** |
| Dedup | SHA-256 within-tick + `catalogue.is_known()` cross-tick | **Done (P6)** |
| Validate | Extension/format allowlist → `_errors/` | **Done (P2)** |
| Stage | Atomic copy to `_staging/` + ffprobe | **Done (P2)** |
| **Audio Analysis** | **YAMNet + AudioCLIP always; Whisper if speech; Essentia if music** | **Planned (P7)** |
| Enrich | Claude API synthesises AnalysisResult into metadata | **P3 done; prompt rewrite in P7** |
| Embed | iXML/BWF · ID3 · XMP sidecar | **Done (P4)** |
| Route | Rules engine → target path | **Done (P5)** |
| Deliver | Atomic move → basehead_import_path | **Done (P5)** |
| Catalogue | SQLite upsert + FTS5 index | **Done (P6); migration in P7** |
| Report | summary.json + ingest.log (JSONL) | **Done (P2)** |

After audio analysis (P7), tick.py carries `audio_result` as the 6th element of the staged tuples through steps 7–11 so catalogue upsert can write all analysis columns.

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
3. SHA-256 dedup: within-tick (same hash twice → skip) + `catalogue.is_known()` cross-tick
4. Extension allowlist (`ingest.py:ALLOWED_EXTENSIONS`) → rejected files moved to `_errors/`
5. `stage_file()` → atomic copy to `_staging/`, collision-safe; `ffprobe.extract()` runs; src unlinked from inbox only after successful stage

Events written to `<library_root>/ingest.log` (JSONL). Status values: `staged` | `rejected` | `error` | `skipped_known`

---

## Audio Analysis Pipeline (P7 — planned)

**Package:** `soundagent/audio_analysis/`

### AnalysisResult dataclass (`result.py`)

```python
@dataclass
class AnalysisResult:
    file_hash: str
    content_type: str                    # "speech" | "music" | "sfx_or_field"
    yamnet_classes: list[dict]           # [{"class": str, "score": float}, ...]
    yamnet_embedding: list[float] | None
    whisper_language: str | None
    whisper_summary: str | None
    audioclip_matches: dict[str, float]  # {prompt: score}
    essentia_bpm: float | None
    essentia_bpm_confidence: float | None
    essentia_key: str | None
    essentia_mood: dict[str, float] | None
    essentia_genre: dict[str, float] | None
    essentia_loudness: float | None
    analysis_duration_s: float
    models_run: list[str]
    models_failed: list[str]
    fallback_only: bool
```

`AnalysisResult.fallback(file_hash)` returns the zero-state with `fallback_only=True`.

### pipeline.py

```python
def analyse(filepath: str, file_hash: str, audio_cfg: dict,
            duration_s: float = 0.0, anthropic_api_key: str = "") -> AnalysisResult:
```

Runs if `audio_cfg.get("enabled", True)` — otherwise returns `AnalysisResult.fallback()` immediately. Long files (`duration_s > max_analysis_duration_s`): YAMNet/AudioCLIP truncate to 60s; Whisper/Essentia skip. Each model wrapped in `try/except Exception` — failure logged, model added to `models_failed`, pipeline continues.

### Model details

| Model | Library | Runs when | Key output |
|---|---|---|---|
| YAMNet | tensorflow, tensorflow-hub | Always | Top-N sound event classes + content_type routing |
| AudioCLIP | torch, AudioCLIP (source) | Always (if weights found) | {prompt: similarity_score} for 21 configurable text prompts |
| Whisper | openai-whisper | content_type=="speech" OR speech_score > speech_threshold | language code, transcript summary |
| Essentia | essentia | content_type=="music" | BPM, key, mood scores, genre scores |

**Preprocessing** (`preprocessor.py`):
- `to_wav(filepath, tmp_dir, sample_rate)` — subprocess ffmpeg; 16kHz for YAMNet/Whisper, 44kHz for AudioCLIP
- `load_waveform_float32(wav_path)` — soundfile first, scipy fallback, normalises to float32 [-1, 1]
- `truncate_waveform(samples, sample_rate, max_seconds)` — slices waveform; logs WARNING when truncating

**AudioCLIP**: weights must be at `audio_cfg["audioclip_weights_path"]` (default `models/audioclip/AudioCLIP.pt`). First-call check: if path missing → log once, raise RuntimeError (caught by pipeline). Default prompt list: 21 environment/texture descriptors (configurable via `audioclip_prompts`). Returns top-8 matches above `audioclip_min_score`.

**Whisper**: For transcripts >30 words → calls Claude with a minimal single-turn prompt for a 1-sentence summary (≤20 words). Best-effort — no retry; skipped if no API key.

**Model weights**:
```
models/
  audioclip/
    AudioCLIP.pt        ← manual download (~800MB)
  .gitkeep
.cache/
  yamnet/               ← TF Hub auto-cache (~25MB)
```

---

## Enrichment pipeline (P3 — updated in P7)

**File:** `soundagent/enrichment.py`

### Current signature (P3)
```python
enrich(filename, file_hash, meta, cfg, cache) -> EnrichmentResult
```

### New signature (P7)
```python
enrich(filename, file_hash, meta, analysis_result, cfg, cache) -> EnrichmentResult
```

`analysis_result` accessed via duck typing; `TYPE_CHECKING` guard prevents circular import.

**Cache** (`EnrichmentCache`): JSON file keyed by SHA-256. New constructor parameter `run_on_existing: bool = False`. When `True`, `get()` returns `None` for cached entries lacking `content_type` (forcing re-enrichment with new model data).

**Prompt** (`_build_prompt(filename, meta, analysis_result) -> str`): Replaces the static `_PROMPT` constant. Conditionally includes YAMNet, AudioCLIP, Whisper, Essentia sections based on `analysis_result`. If `analysis_result.fallback_only`, includes a note instructing lower confidence scores.

**New Claude output fields** (P7 — `_validate()` updated):
- `enrichment_confidence` (replaces `confidence` in JSON key)
- `musical_key` (maps to `key` in `EnrichmentResult`)
- `usage_suggestions` — list of 1–3 use-context strings
- `notes` — free-form cataloguer note or null
- `language` — ISO code if speech detected

**EnrichmentResult** — new optional fields added with defaults:
```python
content_type: Optional[str] = None         # from AnalysisResult
usage_suggestions: list[str] = []
notes: Optional[str] = None
language: Optional[str] = None             # whisper_language
```

**Expanded categories (P7)**:
```python
VALID_SUBCATEGORIES = {
    "field":     {"nature", "urban", "industrial", "interior"},
    "sfx":       {"impacts", "ambience", "foley", "designed"},
    "music":     {"loops", "stems", "beds", "stingers"},
    "broadcast": {"idents", "vo", "transitions"},
    "voice":     {"dialogue", "narration", "interview", "speech"},   # NEW
    "ambience":  {"nature", "urban", "indoor", "mixed"},             # NEW
}
```

New categories route to auto-created subfolders via `router.py`'s existing `mkdir(parents=True)` call. `ucs.py` maps unknown (category, subcategory) pairs to `"UNCL"` — no ucs.py changes needed.

**API call**: `max_tokens` raised to 2048 for new prompt size.

---

## SQLite Catalogue (P6 — migration in P7)

**File:** `soundagent/catalogue.py`  
**Database:** `<library_root>/soundlibrary.db` (WAL mode, FK enforcement)

`open_catalogue(library_root) -> Catalogue` is the entry point. Schema applied idempotently on first connect; `_migrate()` called after to handle existing databases.

### Migration (`_migrate()`)
Called from `_init_schema()` after the main `executescript`. Two stages:
1. `PRAGMA table_info(enrichment)` → `ALTER TABLE enrichment ADD COLUMN {name} {type}` for each of the 14 new columns not yet present
2. FTS rebuild detection: `SELECT usage_suggestions FROM fts_search LIMIT 1` → if `OperationalError`: drop triggers, drop fts_search, recreate with 5-column definition (`description`, `tags`, `usage_suggestions`, `notes` + `hash UNINDEXED`), repopulate from enrichment, recreate triggers

### Schema

| Table | Key | Purpose |
|---|---|---|
| `files` | `hash TEXT PK` | One row per unique file — technical + routing metadata |
| `enrichment` | `hash FK` | Claude + audio analysis result (26 columns total after P7) |
| `ingest_log` | `id AUTOINCREMENT` | Structured append-only event log |
| `fts_search` | FTS5 virtual | Content-indexed over `enrichment(description, tags, usage_suggestions, notes)` |

New enrichment columns (P7 additions):
```
content_type TEXT       yamnet_classes TEXT (JSON)     audioclip_matches TEXT (JSON)
whisper_summary TEXT    whisper_language TEXT           essentia_bpm REAL
essentia_key TEXT       essentia_mood TEXT (JSON)       essentia_genre TEXT (JSON)
models_run TEXT (JSON)  models_failed TEXT (JSON)       analysis_duration_s REAL
usage_suggestions TEXT (JSON)                           notes TEXT
```

### Key methods

| Method | Notes |
|---|---|
| `is_known(hash)` | `True` if file has been fully delivered (`library_path IS NOT NULL`) |
| `upsert_file(...)` | ON CONFLICT: updates `last_seen`, preserves existing `library_path` via COALESCE |
| `upsert_enrichment(...)` | 26 columns; list/dict fields JSON-serialised; ON CONFLICT replaces all |
| `log_event(filename, hash, source, status, **detail)` | `detail` serialised as JSON blob |
| `search(query, category, content_type, whisper_language, min_confidence, …)` | FTS5 MATCH when `query` given; plain SQL filters otherwise |
| `integrity_check()` | Runs `PRAGMA integrity_check`; logs error and returns False on failure |

**CLI query filters (P7 additions):**
```
--content-type TYPE   AND e.content_type = ?
--language LANG       AND e.whisper_language = ?
--confidence-min N    AND e.confidence >= ?
```

---

## Planned modules (not yet built)

| Module | Phase | Purpose |
|---|---|---|
| `soundagent/audio_analysis/` (full package) | P7 | ML audio analysis pipeline |
| `soundagent/api.py` | P8 | FastAPI search server |

---

## Key constraints to remember

- **All ML imports** (`tensorflow`, `whisper`, `torch`, `AudioCLIP`, `essentia`) must be **inside function bodies** — never at module level. Missing libraries log once and the model skips.
- **rclone mount on Windows** requires WinFsp (FUSE layer). Sync mode works without it.
- **WebDAV server** must start and stop cleanly with the agent process — lifecycle tied to tick in Cowork context.
- **Basehead iXML import fields** are undocumented. UCS field mapping (P4) must be validated empirically against a live Basehead instance before considering it done.
- **Non-ASCII filenames** in iXML have known edge cases — test with multilingual content in P4.
- **`_inbox/` is the only handoff point** between adapters and the rest of the pipeline. Adapters must not write anywhere else.
- **essentia is Linux/macOS only** — Windows users get a graceful skip, not an error.
- **Model weights must never be committed** — `models/**` is gitignored; `models/.gitkeep` keeps the directory tracked.
- **FTS5 tables cannot be ALTERed** — migration must drop and recreate the virtual table and all three triggers.
