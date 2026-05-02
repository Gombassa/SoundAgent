# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SoundAgent is a tick-based Python agent that ingests audio files from multiple sources, analyses them with local ML models, enriches them via the Claude API, embeds standardised metadata, routes them into a structured library, and delivers them to Basehead Ultra for search and spotting.

**Status:** P1–P9 complete and committed. Hybrid UCS+slug file rename feature added post-P9.

## Commands

```bash
python -m venv .venv && .venv\Scripts\activate   # create env (Windows)
pip install -r requirements.txt
scripts\install_audio_deps.bat                   # install ML model dependencies

python -m soundagent tick                         # run one agent tick
python -m soundagent tick --dry-run              # log intended actions, no filesystem writes
python -m soundagent init                        # create folder hierarchy from config

python -m soundagent query rain water            # FTS search (description + tags)
python -m soundagent query --category field --min-duration 30 --max-duration 120
python -m soundagent query --content-type music --min-bpm 120 --max-bpm 140
python -m soundagent query --confidence-min 0.8 --limit 20
python -m soundagent query --language en --source local --json

python -m soundagent webdav start                # start WebDAV server as background process
python -m soundagent webdav stop
python -m soundagent webdav status

pytest                                           # run all tests
pytest tests/test_ingest.py                      # single test file
uvicorn soundagent.api:app --reload             # Phase 9 search UI dev server
```

## Architecture

### Tick pipeline (one agent execution)

Every tick runs this sequence in order. Each step is independent and can fail gracefully without aborting the whole tick:

```
TICK START        → Cowork fires agent process
1  HEALTH         → Check each source adapter; skip unavailable, log warning
2  SCAN           → All active adapters deliver files to /_inbox/
3  DEDUP          → SHA-256 hash → check SQLite → skip known files
4  VALIDATE       → Extension/format allowlist → reject to /_errors/
5  STAGE          → Atomic copy to /_staging/ + ffprobe technical metadata
6  AUDIO ANALYSIS → YAMNet + AudioCLIP always; Whisper if speech; Essentia if music
7  ENRICH         → Claude API synthesises analysis results + suggested_filename
7a RENAME         → renamer.py: UCS+slug filename; original preserved in iXML + catalogue
8  EMBED          → Write iXML/BWF (WAV) · ID3 (MP3) · XMP sidecar; ORIGFILENAME in iXML
9  ROUTE          → Rules engine: enriched metadata → target library path
10 DELIVER        → Atomic move → Basehead import folder, fully tagged
11 CATALOGUE      → SQLite upsert + FTS5 index update
12 REPORT         → Tick summary → Cowork log + summary.json
TICK END          → Exit 0 (clean) or exit 1 (partial failure)
```

If all audio analysis models fail or `audio_analysis.enabled: false` → step 6 produces a fallback result → Claude enrichment runs on filename + ffprobe only (identical to pre-integration behaviour). The pipeline never stalls due to model failures.

### Audio analysis package (`soundagent/audio_analysis/`)

| Module | Role |
|---|---|
| `result.py` | `AnalysisResult` dataclass + `AnalysisResult.fallback()` factory |
| `preprocessor.py` | ffmpeg-based conversion (16kHz + 44kHz WAV), waveform loading, truncation |
| `yamnet_analyzer.py` | YAMNet (TF Hub) — sound event detection, content-type routing |
| `whisper_analyzer.py` | Whisper — transcription + language detection (speech files only) |
| `audioclip_analyzer.py` | AudioCLIP — zero-shot semantic tagging against text prompts |
| `essentia_analyzer.py` | Essentia MusicExtractor — BPM, key, mood, genre (music files only) |
| `pipeline.py` | Orchestrator: runs all models, catches failures, returns AnalysisResult |

All ML imports (`tensorflow`, `whisper`, `torch`, `AudioCLIP`, `essentia`) are **inside function bodies** — missing libraries log a warning and the model is skipped; they never crash the agent.

Content-type routing from YAMNet determines which specialist models run: `"speech"` → Whisper; `"music"` → Essentia. AudioCLIP always runs (if weights available). Files longer than `max_analysis_duration_s` (default 120s): YAMNet/AudioCLIP run on first 60s; Whisper/Essentia skip.

AudioCLIP weights must be downloaded manually to `models/audioclip/AudioCLIP.pt` (see README.md). The `models/` directory is gitignored; `models/.gitkeep` keeps the directory in the repo.

### File renamer (`soundagent/renamer.py`)

Runs as step 7a between ENRICH and EMBED. Generates hybrid UCS+slug filenames in the format:

```
{UCS_CATID}_{descriptive-slug}_{sample_rate}k{bit_depth}b.{ext}
```

Examples: `WTHR_rain-woodland-wind-light_96k24b.wav`, `AMB_traffic-exterior-busy_48k.mp3`

- `suggested_filename` (UCS code + slug, no suffix/ext) comes from the Claude API response and is cached with the enrichment result.
- `original_filename` (the staged name before rename) is set at runtime, stored in iXML `ORIGFILENAME` and the `files.original_filename` catalogue column.
- Collision handling: appends `_2`, `_3` etc. before the extension.
- Fallback: if `suggested_filename` is absent, sanitises the original stem + technical suffix and logs a warning. Never raises.

### Source adapters (all converge on `/_inbox/`)

| Adapter | Technology | Use case |
|---|---|---|
| `local` | watchdog | Local folders, DAW export paths |
| `network` | watchdog + availability check | SMB/NFS mapped paths, NAS |
| `rclone` | rclone sync or mount | 70+ cloud providers (S3, GDrive, OneDrive, etc.) |
| `webdav` | wsgidav background service | Mobile: iOS Files app, Android, field recorder apps |

The adapter base class provides a common interface; the agent is source-agnostic once files land in inbox.

### Folder hierarchy

```
/SoundLibrary/
├─ _inbox/          ← all adapters deliver here
├─ _staging/        ← atomic copy during processing
├─ field/nature/  sfx/impacts/  music/loops/  broadcast/idents/  voice/dialogue/  (etc.)
├─ unclassified/    ← low-confidence enrichment fallback
├─ _errors/         ← format/hash failures, quarantined with source annotation
├─ archive/
├─ soundlibrary.db  ← SQLite catalogue (SHA-256 primary key, FTS5 index)
├─ soundagent.log
└─ summary.json     ← per-tick structured report
```

### Configuration

Two-layer config: YAML file (sources, paths, intervals) overridden by environment variables (API keys, adapter flags). The YAML `sources` block is a named list of adapter entries; each has `type: local|network|rclone|webdav` plus type-specific fields.

Key `audio_analysis` config block:

```yaml
audio_analysis:
  enabled: true
  audioclip_weights_path: models/audioclip/AudioCLIP.pt
  whisper_model_size: base          # tiny | base | small | medium | large
  yamnet_cache_dir: .cache/yamnet
  yamnet_top_n: 10
  yamnet_min_score: 0.05
  audioclip_min_score: 0.2
  speech_threshold: 0.2             # YAMNet speech score to trigger Whisper
  music_threshold: 0.3              # YAMNet music score to trigger Essentia
  max_analysis_duration_s: 120
  run_on_existing: false            # re-analyse catalogued files lacking analysis data
```

### Claude enrichment (Phase 3 — updated)

- Model: `claude-sonnet-4-6`
- Claude's role is now **synthesis**, not inference: receives `AnalysisResult` alongside ffprobe metadata
- New output schema: `category`, `subcategory`, `description`, `tags` (max 12), `mood`, `energy`, `usage_suggestions` (1–3 contexts), `bpm`, `musical_key`, `language`, `enrichment_confidence`, `notes`, `suggested_filename`
- Expanded categories: `field | sfx | music | broadcast | voice | ambience`
- Confidence scoring: analysis ran + clear detections → 0.75–0.95; fallback only + poor filename → 0.1–0.35
- Enrichment cache: keyed on SHA-256; `run_on_existing=True` re-enriches files lacking analysis data

### Metadata embedding (Phase 4)

- WAV: iXML/BWF chunk via `bwfmetaedit` (external CLI) or `soundfile`
- MP3: ID3 tags via `mutagen`
- Other formats: XMP sidecar file
- UCS field mapper converts enrichment output to UCS-compatible layout for Basehead import

### Search UI (Phase 9)

FastAPI + HTMX app (`soundagent/api.py`). Config loaded from `SOUNDAGENT_CONFIG` env var (default `config.yaml`).

Routes:
- `GET /` — index with filter dropdowns and total count
- `GET /search` — HTMX partial: FTS + filter results (HTML fragment)
- `GET /file/{hash}` — detail view for a single file
- `GET /audio/{hash}` — stream audio file from library path
- `GET /export.csv` — CSV export of current search results

Filters: `q` (FTS), `category`, `content_type`, `source`, `min_duration`, `max_duration`, `min_bpm`, `max_bpm`, `min_confidence`, `limit` (default 200; 5000 for CSV).

### SQLite catalogue (Phase 6 — updated)

`soundlibrary.db` in `library_root`. Primary key is SHA-256 hash. Tables: `files`, `enrichment`, `ingest_log`. FTS5 virtual table `fts_search` indexes `description + tags + usage_suggestions + notes`; kept in sync via triggers. `_migrate()` in `Catalogue._init_schema()` handles schema evolution via `ALTER TABLE` for new columns + FTS5 rebuild. `open_catalogue(library_root)` is the public entry point.

`files` table extra columns (post-P9): `original_filename` — the staged filename before UCS rename; preserved on first insert via `COALESCE` in the conflict clause.

Enrichment columns (14): `content_type`, `yamnet_classes`, `audioclip_matches`, `whisper_summary`, `whisper_language`, `essentia_bpm`, `essentia_key`, `essentia_mood`, `essentia_genre`, `models_run`, `models_failed`, `analysis_duration_s`, `usage_suggestions`, `notes`.

## Key dependencies

**Core Python packages:** `anthropic`, `pyyaml`, `watchdog`, `ffmpeg-python`, `mutagen`, `wsgidav`, `aiofiles`, `tenacity`, `fastapi`, `uvicorn`

**Audio analysis (optional — graceful skip if missing):**
- `tensorflow>=2.13`, `tensorflow-hub>=0.14` — YAMNet
- `openai-whisper` — speech transcription
- `torch>=2.0`, `torchaudio>=2.0` — AudioCLIP inference
- `AudioCLIP` — source install required (see README.md)
- `essentia` — music analysis (Linux/macOS; skip gracefully on Windows)
- `soundfile>=0.12`, `scipy>=1.11` — WAV loading

**External tools (must be on PATH):**
- `ffprobe` (FFmpeg) — audio technical metadata extraction and audio conversion for ML models
- `rclone` — cloud sync/mount (required only if rclone adapter is configured)
- `WinFsp` — FUSE layer for rclone mount mode on Windows
- `bwfmetaedit` — BWF iXML write and validation

**Front-end:** Basehead Ultra (external application); agent delivers files to Basehead's configured import/watch folder.

**Model weights (not in repo):**
- AudioCLIP: `models/audioclip/AudioCLIP.pt` — manual download (~800MB, see README.md)
- YAMNet: auto-downloads to `.cache/yamnet/` on first run (~25MB)
- Whisper base: auto-downloads on first run (~145MB)

## Important constraints

- All ML library imports (`tensorflow`, `whisper`, `torch`, `AudioCLIP`, `essentia`) must be inside function bodies — never at module level. Missing libraries log once and the model skips cleanly.
- Rclone mount mode requires WinFsp on Windows — document this dependency prominently for users.
- WebDAV server lifecycle must be tied to the agent process (clean start/stop with tick).
- Network/cloud adapters must fail gracefully (skip + retry queue) — never block the tick.
- iXML spec has edge cases with non-ASCII characters; test with multilingual filenames early.
- Basehead's iXML import field mapping is undocumented — requires empirical validation against a live Basehead instance.
- Model weights must never be committed: `models/**` is gitignored; `models/.gitkeep` keeps the directory.
- essentia is Linux/macOS only — Windows users get graceful skip, not an error.

## Gotchas

- **`New-Item -ItemType Directory` on a dotfile path creates a directory, not a file.** Running `New-Item -ItemType Directory -Path "models\.gitkeep"` silently creates a *directory* named `.gitkeep`. Subsequent attempts to write a file at that path get "Access is denied". Fix: `Remove-Item -Recurse -Force` the directory first, then `Set-Content` to create the file.
- **Starlette 1.0.0 changed `TemplateResponse` — `request` is now the first positional arg, not inside the context dict.** Call as `templates.TemplateResponse(request, "name.html", {"key": val})`. The old form `templates.TemplateResponse("name.html", {"request": request, ...})` passes the context dict as `name`, causing a Jinja2 `TypeError` on Python 3.14.
- **`unittest.mock.patch` requires the target to be a module-level attribute.** Patching `module.attr` raises `AttributeError` if `attr` was imported inside a function body. For `audio_analysis/pipeline.py`: sub-module imports (`preprocessor`, `yamnet_analyzer`, etc.) are at module level so they can be patched in tests; ML library imports (`tensorflow`, `torch`, `whisper`, `essentia`) stay inside function bodies to avoid `ImportError` when libraries aren't installed.
