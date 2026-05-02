# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SoundAgent is a tick-based Python agent that ingests audio files from multiple sources, enriches them via the Claude API, embeds standardised metadata, routes them into a structured library, and delivers them to Basehead Ultra for search and spotting.

**Status:** Pre-implementation. The plan is in `soundagent-plan.jsx` (React UI for the build plan). The Python codebase is being built from scratch.

## Commands

Once the Python package is in place, standard commands will be:

```bash
python -m venv .venv && .venv\Scripts\activate   # create env (Windows)
pip install -r requirements.txt

python -m soundagent tick                         # run one agent tick
python -m soundagent tick --dry-run              # log intended actions, no filesystem writes
python -m soundagent query --tag rain            # CLI catalogue search
python -m soundagent init                        # create folder hierarchy from config

pytest                                           # run all tests
pytest tests/test_ingest.py                      # single test file
uvicorn soundagent.api:app --reload             # Phase 8 search UI dev server
```

## Architecture

### Tick pipeline (one agent execution)

Every tick runs this sequence in order. Each step is independent and can fail gracefully without aborting the whole tick:

```
TICK START   → Cowork fires agent process
1 HEALTH     → Check each source adapter; skip unavailable, log warning
2 SCAN       → All active adapters deliver files to /_inbox/
3 DEDUP      → SHA-256 hash → check SQLite → skip known files
4 VALIDATE   → Extension/format allowlist → reject to /_errors/
5 STAGE      → Atomic copy to /_staging/ + ffprobe technical metadata
6 ENRICH     → Claude API: category, subcategory, tags, description, mood, BPM/key
7 EMBED      → Write iXML/BWF (WAV) · ID3 (MP3) · XMP sidecar
8 ROUTE      → Rules engine: enriched metadata → target library path
9 DELIVER    → Atomic move → Basehead import folder, fully tagged
10 CATALOGUE → SQLite upsert + FTS5 index update
11 REPORT    → Tick summary → Cowork log + summary.json
TICK END     → Exit 0 (clean) or exit 1 (partial failure)
```

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
├─ field/nature/  sfx/impacts/  music/loops/  broadcast/idents/  (etc.)
├─ unclassified/    ← low-confidence enrichment fallback
├─ _errors/         ← format/hash failures, quarantined with source annotation
├─ archive/
├─ soundlibrary.db  ← SQLite catalogue (SHA-256 primary key, FTS5 index)
├─ soundagent.log
└─ summary.json     ← per-tick structured report
```

### Configuration

Two-layer config: YAML file (sources, paths, intervals) overridden by environment variables (API keys, adapter flags). The YAML `sources` block is a named list of adapter entries; each has `type: local|network|rclone|webdav` plus type-specific fields.

### Claude enrichment (Phase 3)

- Model: `claude-sonnet-4` (current plan notation; use latest Sonnet)
- Output: structured JSON — category, subcategory, description, tags, mood, energy, BPM/key (music only)
- Enrichment is cached by SHA-256 hash to avoid reprocessing unchanged files
- Confidence threshold: files below threshold route to `/unclassified/` rather than failing

### Metadata embedding (Phase 4)

- WAV: iXML/BWF chunk via `bwfmetaedit` (external CLI) or `soundfile`
- MP3: ID3 tags via `mutagen`
- Other formats: XMP sidecar file
- UCS field mapper converts enrichment output to UCS-compatible layout for Basehead import

### SQLite catalogue (Phase 6)

Primary key is SHA-256 hash. Key tables: `files`, `tags`, `enrichment`, `ingest_log`, `source_log`, `errors`. FTS5 index on `description + tags` for full-text search. Migrations managed by Alembic.

## Key dependencies

**Python packages:** `anthropic`, `pyyaml`, `watchdog`, `ffmpeg-python`, `mutagen`, `wsgidav`, `aiofiles`, `tenacity`, `fastapi`, `uvicorn`, `alembic`

**External tools (must be on PATH):**
- `ffprobe` (FFmpeg) — audio technical metadata extraction
- `rclone` — cloud sync/mount (required only if rclone adapter is configured)
- `WinFsp` — FUSE layer for rclone mount mode on Windows
- `bwfmetaedit` — BWF iXML write and validation

**Front-end:** Basehead Ultra (external application); agent delivers files to Basehead's configured import/watch folder.

## Important constraints

- Rclone mount mode requires WinFsp on Windows — document this dependency prominently for users.
- WebDAV server lifecycle must be tied to the agent process (clean start/stop with tick).
- Network/cloud adapters must fail gracefully (skip + retry queue) — never block the tick.
- iXML spec has edge cases with non-ASCII characters; test with multilingual filenames early.
- Basehead's iXML import field mapping is undocumented — requires empirical validation against a live Basehead instance.
