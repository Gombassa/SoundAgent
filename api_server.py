"""
SoundAgent Control Panel API
Run with: uvicorn api_server:app --host 0.0.0.0 --port 8765 --reload

Install deps:
    pip install fastapi uvicorn[standard] pydantic
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Literal
import shutil, subprocess, sys, time, json, pathlib, threading, urllib.request, yaml

# ── Config ─────────────────────────────────────────────────────────────────────

_ROOT    = pathlib.Path(__file__).parent
DB_PATH  = _ROOT / "data" / "ui_config.json"

# ── Tick / service process state ──────────────────────────────────────────────

_tick_proc:   subprocess.Popen | None = None
_tick_paused: bool                    = False
_ollama_proc: subprocess.Popen | None = None  # only set if we started it ourselves


def _cfg_yaml() -> dict:
    try:
        with open(_ROOT / "config.yaml") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _ensure_services() -> dict:
    """Start any background services the tick needs. Returns per-service status."""
    global _ollama_proc
    cfg = _cfg_yaml()
    enrichment = cfg.get("enrichment", {})
    provider   = enrichment.get("provider", "claude")

    if provider != "ollama":
        return {}

    ollama_url = enrichment.get("ollama_url", "http://localhost:11434")
    try:
        urllib.request.urlopen(ollama_url, timeout=2)
        return {"ollama": "running"}
    except Exception:
        pass

    # Ollama not reachable — try to start it
    try:
        _ollama_proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait up to 6 s for it to come up
        for _ in range(6):
            time.sleep(1)
            try:
                urllib.request.urlopen(ollama_url, timeout=1)
                return {"ollama": "started"}
            except Exception:
                pass
        return {"ollama": "starting"}  # still booting — tick will retry
    except FileNotFoundError:
        return {"ollama": "not_found"}  # ollama not on PATH; tick falls back to Claude
DB_PATH.parent.mkdir(exist_ok=True)

app = FastAPI(title="SoundAgent Control Panel API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Persistence helpers ────────────────────────────────────────────────────────

_lock = threading.Lock()

def _load() -> dict:
    if DB_PATH.exists():
        with open(DB_PATH) as f:
            return json.load(f)
    return _defaults()

def _save(data: dict):
    with _lock:
        with open(DB_PATH, "w") as f:
            json.dump(data, f, indent=2)

def _defaults() -> dict:
    return {
        "sources": [
            {"id": 1, "path": "D:\\Field Recordings",                    "type": "local",  "enabled": True},
            {"id": 2, "path": "C:\\Users\\robin\\Music\\Field Recordings","type": "local",  "enabled": True},
            {"id": 3, "path": "G:\\My Drive\\Field recordings",          "type": "rclone", "enabled": True},
            {"id": 4, "path": "G:\\My Drive\\To sort",                   "type": "rclone", "enabled": False},
        ],
        "categories": [
            {"id": "atmos",        "label": "Atmosphere",   "group": "Ambience",   "enabled": True},
            {"id": "room",         "label": "Room Tone",    "group": "Ambience",   "enabled": True},
            {"id": "silence",      "label": "Silence",      "group": "Ambience",   "enabled": False},
            {"id": "rain",         "label": "Rain",         "group": "Nature",     "enabled": True},
            {"id": "wind",         "label": "Wind",         "group": "Nature",     "enabled": True},
            {"id": "water",        "label": "Water",        "group": "Nature",     "enabled": True},
            {"id": "birds",        "label": "Birds",        "group": "Nature",     "enabled": True},
            {"id": "insects",      "label": "Insects",      "group": "Nature",     "enabled": False},
            {"id": "thunder",      "label": "Thunder",      "group": "Nature",     "enabled": False},
            {"id": "fire",         "label": "Fire",         "group": "Nature",     "enabled": False},
            {"id": "traffic",      "label": "Traffic",      "group": "Urban",      "enabled": True},
            {"id": "crowd",        "label": "Crowd",        "group": "Urban",      "enabled": True},
            {"id": "construction", "label": "Construction", "group": "Urban",      "enabled": False},
            {"id": "transport",    "label": "Transport",    "group": "Urban",      "enabled": False},
            {"id": "machinery",    "label": "Machinery",    "group": "Industrial", "enabled": True},
            {"id": "electrical",   "label": "Electrical",   "group": "Industrial", "enabled": False},
            {"id": "hvac",         "label": "HVAC",         "group": "Industrial", "enabled": False},
            {"id": "voice",        "label": "Voice",        "group": "Human",      "enabled": True},
            {"id": "foley",        "label": "Foley",        "group": "Human",      "enabled": True},
            {"id": "footsteps",    "label": "Footsteps",    "group": "Human",      "enabled": True},
            {"id": "music",        "label": "Music",        "group": "Music",      "enabled": True},
            {"id": "tonal",        "label": "Tonal / Drone","group": "Music",      "enabled": False},
            {"id": "rhythmic",     "label": "Rhythmic",     "group": "Music",      "enabled": False},
        ],
        "models": [
            {"id": "yamnet",    "name": "YAMNet",    "desc": "Audio event classification · AudioSet",  "enabled": True,  "threshold": 0.40, "status": "ready"},
            {"id": "whisper",   "name": "Whisper",   "desc": "Speech detection & transcription",       "enabled": True,  "threshold": 0.50, "status": "ready"},
            {"id": "audioclip", "name": "AudioCLIP", "desc": "Semantic audio-text embedding",          "enabled": True,  "threshold": 0.35, "status": "ready"},
            {"id": "essentia",  "name": "Essentia",  "desc": "Music analysis & feature extraction",    "enabled": False, "threshold": 0.45, "status": "disabled"},
        ],
    }

# ── Schemas ────────────────────────────────────────────────────────────────────

class SourceCreate(BaseModel):
    path: str
    type: Literal["local", "rclone", "webdav"]
    enabled: bool = True

class SourcePatch(BaseModel):
    path: Optional[str] = None
    type: Optional[Literal["local", "rclone", "webdav"]] = None
    enabled: Optional[bool] = None

class CategoryCreate(BaseModel):
    id: str
    label: str
    group: str
    enabled: bool = True

class CategoryPatch(BaseModel):
    enabled: Optional[bool] = None
    label: Optional[str] = None

class ModelPatch(BaseModel):
    enabled: Optional[bool] = None
    threshold: Optional[float] = None

# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.2.0"}

# ── Sources ────────────────────────────────────────────────────────────────────

@app.get("/api/sources")
def list_sources():
    return _load()["sources"]

@app.post("/api/sources", status_code=201)
def add_source(body: SourceCreate):
    data = _load()
    new_id = max((s["id"] for s in data["sources"]), default=0) + 1
    src = {"id": new_id, **body.model_dump()}
    data["sources"].append(src)
    _save(data)
    # TODO: register with watchdog / rclone / wsgidav watcher
    return src

@app.patch("/api/sources/{source_id}")
def patch_source(source_id: int, body: SourcePatch):
    data = _load()
    src = next((s for s in data["sources"] if s["id"] == source_id), None)
    if not src:
        raise HTTPException(404, "Source not found")
    update = body.model_dump(exclude_none=True)
    src.update(update)
    _save(data)
    # TODO: enable/disable watchdog observer for this path
    return src

@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: int):
    data = _load()
    before = len(data["sources"])
    data["sources"] = [s for s in data["sources"] if s["id"] != source_id]
    if len(data["sources"]) == before:
        raise HTTPException(404, "Source not found")
    _save(data)
    # TODO: deregister watchdog observer

# ── Categories ─────────────────────────────────────────────────────────────────

@app.get("/api/categories")
def list_categories():
    return _load()["categories"]

@app.patch("/api/categories/{cat_id}")
def patch_category(cat_id: str, body: CategoryPatch):
    data = _load()
    cat = next((c for c in data["categories"] if c["id"] == cat_id), None)
    if not cat:
        raise HTTPException(404, "Category not found")
    cat.update(body.model_dump(exclude_none=True))
    _save(data)
    return cat

# ── Models ─────────────────────────────────────────────────────────────────────

@app.get("/api/models")
def list_models():
    return _load()["models"]

@app.patch("/api/models/{model_id}")
def patch_model(model_id: str, body: ModelPatch):
    data = _load()
    model = next((m for m in data["models"] if m["id"] == model_id), None)
    if not model:
        raise HTTPException(404, "Model not found")
    updates = body.model_dump(exclude_none=True)
    if "enabled" in updates:
        updates["status"] = "ready" if updates["enabled"] else "disabled"
    model.update(updates)
    _save(data)
    # TODO: trigger model load/unload in analysis pipeline
    return model

# ── Pipeline status ────────────────────────────────────────────────────────────

@app.get("/api/pipeline/status")
def pipeline_status():
    running = _tick_proc is not None and _tick_proc.poll() is None
    state   = "paused" if _tick_paused else ("processing" if running else "idle")
    return {
        "state": state,
        "queue_depth": 0,       # TODO: count files in _inbox
        "processed_today": 0,   # TODO: query catalogue DB
        "current_file": None,
        "events": [],           # TODO: tail recent catalogue entries
        "uptime_s": int(time.time()),
    }


# ── Tick control ───────────────────────────────────────────────────────────────

@app.post("/api/tick/run")
def tick_run():
    global _tick_proc
    if _tick_paused:
        raise HTTPException(409, "Pipeline is paused — resume first")
    if _tick_proc is not None and _tick_proc.poll() is None:
        raise HTTPException(409, "Tick already running")

    services = _ensure_services()

    _tick_proc = subprocess.Popen(
        [sys.executable, "-m", "soundagent", "tick"],
        cwd=_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "pid": _tick_proc.pid, "services": services}


@app.post("/api/tick/pause")
def tick_pause():
    global _tick_paused
    _tick_paused = True
    if _tick_proc is not None and _tick_proc.poll() is None:
        _tick_proc.terminate()
    return {"ok": True, "state": "paused"}


@app.post("/api/tick/resume")
def tick_resume():
    global _tick_paused
    _tick_paused = False
    return {"ok": True, "state": "idle"}


@app.post("/api/tick/reset")
def tick_reset():
    global _tick_proc, _tick_paused, _ollama_proc
    _tick_paused = False
    if _tick_proc is not None and _tick_proc.poll() is None:
        _tick_proc.terminate()
    _tick_proc = None
    if _ollama_proc is not None and _ollama_proc.poll() is None:
        _ollama_proc.terminate()
    _ollama_proc = None
    try:
        from soundagent.config import load_config
        cfg     = load_config(str(_ROOT / "config.yaml"))
        staging = pathlib.Path(cfg.library_root) / "_staging"
        if staging.exists():
            shutil.rmtree(staging)
            staging.mkdir()
    except Exception:
        pass
    return {"ok": True, "state": "idle"}

# ── Category hint helper (for use in enrichment pipeline) ──────────────────────

def get_active_category_hints() -> str:
    """
    Call this from your enrichment worker to inject UI-configured hints
    into the Claude synthesis prompt.

    Returns a formatted hint string, or empty string if none active.
    """
    cats = _load()["categories"]
    active = [c["label"] for c in cats if c.get("enabled")]
    if not active:
        return ""
    return f"Prioritise these category hints where applicable: {', '.join(active)}."

def get_active_models() -> list[dict]:
    """Return list of enabled model configs for the analysis pipeline."""
    return [m for m in _load()["models"] if m.get("enabled")]

def get_active_sources() -> list[dict]:
    """Return list of enabled sources for the watcher to monitor."""
    return [s for s in _load()["sources"] if s.get("enabled")]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8765, reload=True)