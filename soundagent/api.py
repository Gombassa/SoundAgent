"""FastAPI search interface for the SoundAgent sound library catalogue."""

import csv
import io
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from soundagent.catalogue import open_catalogue
from soundagent.config import load_config

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_JSON_COLS = (
    "tags", "usage_suggestions", "yamnet_classes",
    "audioclip_matches", "models_run", "models_failed",
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _pre_init = hasattr(app.state, "cat")
    if not _pre_init:
        config_path = os.environ.get("SOUNDAGENT_CONFIG", "config.yaml")
        cfg = load_config(config_path)
        app.state.cfg = cfg
        app.state.cat = open_catalogue(cfg.library_root)
    yield
    if not _pre_init:
        app.state.cat.close()


app = FastAPI(title="SoundAgent", lifespan=_lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cat(request: Request):
    return request.app.state.cat


def _dropdown(cat, column: str, table: str = "enrichment") -> list[str]:
    rows = cat._con.execute(
        f"SELECT DISTINCT {column} FROM {table} "
        f"WHERE {column} IS NOT NULL ORDER BY {column}"
    ).fetchall()
    return [r[0] for r in rows]


def _decode(record: dict) -> dict:
    for col in _JSON_COLS:
        if record.get(col) and isinstance(record[col], str):
            try:
                record[col] = json.loads(record[col])
            except Exception:
                pass
    return record


def _search_params(
    q, category, content_type, source,
    min_duration, max_duration, min_bpm, max_bpm, min_confidence, limit,
) -> dict:
    return dict(
        query=q.strip() or None if q else None,
        category=category or None,
        content_type=content_type or None,
        source=source or None,
        min_duration=min_duration,
        max_duration=max_duration,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
        min_confidence=min_confidence,
        limit=limit,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cat = _cat(request)
    total = cat._con.execute(
        "SELECT COUNT(*) FROM files WHERE library_path IS NOT NULL"
    ).fetchone()[0]
    return _TEMPLATES.TemplateResponse(request, "index.html", {
        "categories": _dropdown(cat, "category"),
        "content_types": _dropdown(cat, "content_type"),
        "sources": _dropdown(cat, "source_adapter", table="files"),
        "total": total,
    })


@app.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    content_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_duration: Optional[float] = Query(None),
    max_duration: Optional[float] = Query(None),
    min_bpm: Optional[float] = Query(None),
    max_bpm: Optional[float] = Query(None),
    min_confidence: Optional[float] = Query(None),
    limit: int = Query(200),
):
    cat = _cat(request)
    results = cat.search(**_search_params(
        q, category, content_type, source,
        min_duration, max_duration, min_bpm, max_bpm, min_confidence, limit,
    ))
    return _TEMPLATES.TemplateResponse(request, "_results.html", {
        "results": results,
        "count": len(results),
    })


@app.get("/file/{file_hash}", response_class=HTMLResponse)
async def file_detail(request: Request, file_hash: str):
    cat = _cat(request)
    row = cat._con.execute(
        """
        SELECT f.*, e.category, e.subcategory, e.cat_id, e.description,
               e.tags, e.mood, e.energy, e.bpm, e.key,
               e.confidence, e.low_confidence, e.content_type,
               e.usage_suggestions, e.notes, e.language,
               e.yamnet_classes, e.audioclip_matches,
               e.whisper_summary, e.whisper_language,
               e.essentia_bpm, e.essentia_key,
               e.models_run, e.models_failed
        FROM files f
        LEFT JOIN enrichment e ON e.hash = f.hash
        WHERE f.hash = ?
        """,
        (file_hash,),
    ).fetchone()
    if row is None:
        return HTMLResponse(
            "<p class='p-4 text-red-500 text-sm'>File not found.</p>", status_code=404
        )
    return _TEMPLATES.TemplateResponse(request, "_detail.html", {
        "f": _decode(dict(row)),
    })


@app.get("/audio/{file_hash}")
async def stream_audio(request: Request, file_hash: str):
    cat = _cat(request)
    row = cat._con.execute(
        "SELECT library_path FROM files WHERE hash = ?", (file_hash,)
    ).fetchone()
    if not row or not row[0] or not Path(row[0]).exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(row[0])


@app.get("/export.csv")
async def export_csv(
    request: Request,
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    content_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_duration: Optional[float] = Query(None),
    max_duration: Optional[float] = Query(None),
    min_bpm: Optional[float] = Query(None),
    max_bpm: Optional[float] = Query(None),
    min_confidence: Optional[float] = Query(None),
    limit: int = Query(5000),
):
    cat = _cat(request)
    results = cat.search(**_search_params(
        q, category, content_type, source,
        min_duration, max_duration, min_bpm, max_bpm, min_confidence, limit,
    ))

    cols = [
        "filename", "cat_id", "category", "subcategory", "description", "tags",
        "mood", "energy", "bpm", "key", "confidence", "content_type", "language",
        "usage_suggestions", "notes", "duration_s", "sample_rate", "codec",
        "channels", "file_size", "source_adapter", "library_path", "date_added",
        "whisper_language", "essentia_bpm", "essentia_key", "models_run",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in results:
        row = dict(r)
        for col in ("tags", "usage_suggestions", "models_run"):
            if isinstance(row.get(col), list):
                row[col] = "; ".join(str(x) for x in row[col])
        writer.writerow(row)

    out.seek(0)
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=soundlibrary.csv"},
    )
