# SoundAgent

Tick-based Python agent that ingests audio files from multiple sources, analyses them with local ML models, enriches them via the Claude API, embeds UCS-compatible metadata, and delivers fully tagged files to Basehead Ultra.

Each tick runs the full pipeline: scan → deduplicate → stage → analyse → enrich → rename → embed → route → deliver → catalogue.

---

## Prerequisites

Before installing, make sure the following are available on your system:

| Tool | Purpose | Notes |
|---|---|---|
| Python 3.10–3.12 | Runtime | 3.13+ blocks TensorFlow; use pyenv-win on Windows |
| [FFmpeg](https://ffmpeg.org/download.html) | Audio conversion + metadata | Must be on PATH (`ffmpeg` and `ffprobe`) |
| [fpcalc (Chromaprint)](https://acoustid.org/chromaprint) | Near-duplicate fingerprinting | Place at `tools/fpcalc.exe` or set path in config |
| [bwfmetaedit](https://mediaarea.net/BWFMetaEdit) | BWF/iXML metadata writing (WAV) | Must be on PATH |
| Anthropic API key | Claude enrichment | Set as `ANTHROPIC_API_KEY` env var |

---

## Installation

```bash
# 1. Clone and create virtual environment
git clone https://github.com/yourname/SoundAgent
cd SoundAgent
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 2. Install core dependencies
pip install -r requirements.txt

# 3. Install optional ML model dependencies (audio analysis)
scripts\install_audio_deps.bat   # Windows
# See "Audio Analysis Models" section for manual install steps

# 4. Set up config
copy config.example.yaml config.yaml
# Edit config.yaml — set library_root, sources, and audioclip_weights_path

# 5. Set your API key (do not put this in config.yaml)
# Windows:
set ANTHROPIC_API_KEY=sk-ant-...
# Or create a .env file in the project root:
echo ANTHROPIC_API_KEY=sk-ant-... > .env

# 6. Create the library folder hierarchy
python -m soundagent init

# 7. Run a tick
python -m soundagent tick
```

---

## Configuration

Copy `config.example.yaml` to `config.yaml` and edit the following:

```yaml
library_root: D:\SoundLibrary        # where files, DB, and logs live
basehead_import_path: D:\SoundLibrary # Basehead watches this folder tree

audio_analysis:
  audioclip_weights_path: C:/ML Models/audioclip/AudioCLIP-Partial-Training.pt
  whisper_model: base                 # tiny | base | small | medium | large

duplicate_detection:
  fpcalc_path: tools/fpcalc.exe      # or absolute path, or "fpcalc" if on PATH

sources:
  - name: inbox
    type: local
    path: D:\SoundLibrary_Inbox
    enabled: true
```

**Never put `ANTHROPIC_API_KEY` in `config.yaml`** — use the environment variable or a `.env` file.

Windows paths in YAML should use forward slashes (`C:/ML Models/...`) or escaped backslashes (`C:\\ML Models\\...`).

---

## Audio Analysis Models

SoundAgent uses four local ML models to analyse audio content before Claude enrichment. All models degrade gracefully — if a model is unavailable or fails, the pipeline continues with whatever data is available.

### Model overview

| Model | Library | Purpose | Runs on |
|---|---|---|---|
| YAMNet | tensorflow, tensorflow-hub | Sound event detection; determines content type | Every file |
| Whisper | openai-whisper | Transcription + language detection | Speech files only |
| AudioCLIP | torch + AudioCLIP source | Zero-shot semantic tagging | Every file |
| Essentia | essentia (Linux/macOS) | BPM, key, mood, genre | Music files only |
| librosa | librosa (Windows fallback) | BPM, key (replaces Essentia on Windows) | Music files only |

### Model weights

**YAMNet and Whisper download automatically** on first use:

| Model | Auto-download location | Size |
|---|---|---|
| YAMNet | `%TEMP%\tfhub_modules` (TF Hub cache) | ~25 MB |
| Whisper (base) | `%USERPROFILE%\.cache\whisper` | ~145 MB |

**AudioCLIP weights must be downloaded manually** (~660 MB total). These are large binary files and are not stored inside the project directory — place them in a permanent location on your machine and point `config.yaml` at them.

#### Download

Go to the [AudioCLIP releases page](https://github.com/AndreyGuzhov/AudioCLIP/releases) and download these three files:

| File | Size | Purpose |
|---|---|---|
| `AudioCLIP-Partial-Training.pt` | ~512 MB | Audio-head weights |
| `ESRNXFBSP.pt` | ~119 MB | Audio encoder |
| `bpe_simple_vocab_16e6.txt.gz` | ~1.3 MB | Text vocabulary |

Download the **Partial-Training** weights only. Do not download `AudioCLIP-Full-Training.pt` or `CLIP.pt` — they are not used.

#### Placement

Store the three files together in a permanent directory outside the project, for example:

```
C:\ML Models\audioclip\
    AudioCLIP-Partial-Training.pt
    ESRNXFBSP.pt
    bpe_simple_vocab_16e6.txt.gz
```

Then set the path in `config.yaml`:

```yaml
audio_analysis:
  audioclip_weights_path: C:/ML Models/audioclip/AudioCLIP-Partial-Training.pt
```

The encoder (`ESRNXFBSP.pt`) and vocabulary (`bpe_simple_vocab_16e6.txt.gz`) are discovered automatically from the same directory as `audioclip_weights_path`. No separate config entries are needed for them.

#### AudioCLIP source install

AudioCLIP also requires a source install of the package itself:

```bash
git clone https://github.com/AndreyGuzhov/AudioCLIP
pip install -e ./AudioCLIP
```

Run `scripts\install_audio_deps.bat` to install all ML dependencies in one step (PyTorch, TensorFlow, Whisper, librosa). The script will prompt you to complete the AudioCLIP source install manually.

### Disabling audio analysis

If you want to run SoundAgent without any ML models, set `enabled: false` in config:

```yaml
audio_analysis:
  enabled: false
```

Claude enrichment will run on filename and ffprobe metadata only.

---

## Duplicate Detection

SoundAgent uses two-pass deduplication:

1. **Exact (step 3):** SHA-256 hash checked against the catalogue. Exact matches are quarantined immediately.
2. **Near-duplicate (step 5a):** Chromaprint fingerprint compared against stored fingerprints using Hamming distance. Catches the same recording at different sample rates or formats.

Download `fpcalc` from [acoustid.org/chromaprint](https://acoustid.org/chromaprint) and place it at `tools/fpcalc.exe` (Windows) or set an absolute path:

```yaml
duplicate_detection:
  fpcalc_path: tools/fpcalc.exe
  fingerprint_similarity_threshold: 0.85   # 0.0–1.0; lower = more aggressive
```

Duplicates are moved to `_duplicates/` with a `.duplicate.json` sidecar. If fpcalc is not found, exact-hash dedup still runs; fingerprint matching is skipped with a startup warning.

---

## Commands

```bash
# Core pipeline
python -m soundagent tick                       # run one agent tick
python -m soundagent tick --dry-run             # log intended actions, no writes
python -m soundagent init                       # create library folder hierarchy

# Search the catalogue
python -m soundagent query rain water           # full-text search
python -m soundagent query --category field --min-duration 30 --max-duration 120
python -m soundagent query --content-type music --min-bpm 120 --max-bpm 140
python -m soundagent query --confidence-min 0.8 --limit 20
python -m soundagent query --language en --source local --json

# Duplicates
python -m soundagent duplicates                 # list unresolved duplicates
python -m soundagent duplicates --all           # include resolved

# WebDAV server (mobile ingest — iOS Files, Android, field recorders)
python -m soundagent webdav start
python -m soundagent webdav stop
python -m soundagent webdav status

# Search UI (browser)
uvicorn soundagent.api:app --reload             # http://localhost:8000
```

Use `--config` before the subcommand to specify a non-default config file:

```bash
python -m soundagent --config test_config.yaml tick
```

---

## Source Adapters

Files are ingested from one or more sources and converge on `/_inbox/` before processing.

| Adapter | Type | Use case |
|---|---|---|
| `local` | `type: local` | Local folder, DAW export path |
| `network` | `type: network` | SMB/NFS mapped drive, NAS |
| `rclone` | `type: rclone` | Cloud: S3, Google Drive, OneDrive, Dropbox (70+ providers) |
| `webdav` | `type: webdav` | Mobile: iOS Files app, Android, portable recorders |

Example multi-source config:

```yaml
sources:
  - name: inbox
    type: local
    path: D:\SoundLibrary_Inbox
    enabled: true

  - name: field_nas
    type: network
    path: \\192.168.1.10\recordings
    enabled: true

  - name: cloud_dropbox
    type: rclone
    remote: dropbox
    remote_path: /SoundAgent/inbox
    enabled: false
```

rclone mount mode on Windows requires [WinFsp](https://winfsp.dev/).

---

## Library Structure

```
SoundLibrary/
├─ _inbox/           ← all adapters deliver here
├─ _staging/         ← files held during processing
├─ _duplicates/      ← quarantined exact and near-duplicates
├─ _errors/          ← rejected files (bad format, hash failure)
├─ field/nature/
├─ sfx/impacts/
├─ music/loops/
├─ broadcast/idents/
├─ voice/dialogue/
├─ ambience/
├─ unclassified/     ← low-confidence enrichment fallback
├─ archive/
├─ soundlibrary.db   ← SQLite catalogue (SHA-256 primary key, FTS5)
├─ soundagent.log
└─ summary.json      ← per-tick structured report
```

Delivered files are renamed to a hybrid UCS+slug format:

```
{UCS_CATID}_{descriptive-slug}_{sample_rate}k{bit_depth}b.{ext}

Examples:
  WTHR_rain-woodland-wind-light_96k24b.wav
  AMB_traffic-exterior-busy-urban_48k24b.wav
  PERC_drum-loop-rhythmic-g-major-112bpm_48k16b.wav
```

The original filename is preserved in the iXML `ORIGFILENAME` field and in the catalogue.

---

## Search UI

FastAPI + HTMX browser interface for the catalogue:

```bash
uvicorn soundagent.api:app --reload
# Open http://localhost:8000
```

Filters: free-text (FTS5), category, content type, source, duration, BPM range, confidence, export to CSV.
