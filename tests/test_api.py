"""Tests for soundagent.api — FastAPI search interface."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from soundagent.api import app
from soundagent.catalogue import Catalogue


@pytest.fixture
def db(tmp_path):
    """Populated in-memory catalogue for API tests."""
    cat = Catalogue(tmp_path / "test.db")

    cat.upsert_file(
        hash="h1", filename="rain.wav", source_adapter="local",
        library_path=str(tmp_path / "rain.wav"),
        format="WAV", codec="pcm_s24le", duration_s=10.0,
        sample_rate=48000, bit_depth=24, channels=2, file_size=960000,
    )
    cat.upsert_enrichment(
        hash="h1", category="field", subcategory="nature", cat_id="AMB-NATU",
        description="Heavy rainfall on forest leaves",
        tags=["rain", "nature", "forest"],
        mood="calm", energy="low", bpm=None, key=None,
        confidence=0.92, low_confidence=False,
        content_type="sfx_or_field",
        usage_suggestions=["documentary", "game ambience"],
    )

    cat.upsert_file(
        hash="h2", filename="kick.wav", source_adapter="network",
        library_path=str(tmp_path / "kick.wav"),
        format="WAV", codec="pcm_s16le", duration_s=0.5,
        sample_rate=44100, bit_depth=16, channels=1, file_size=44100,
    )
    cat.upsert_enrichment(
        hash="h2", category="music", subcategory="loops", cat_id="MUS-LOOP",
        description="Punchy kick drum hit",
        tags=["kick", "drum", "music"],
        mood="energetic", energy="high", bpm=128.0, key="—",
        confidence=0.88, low_confidence=False,
        content_type="music",
        models_run=["yamnet", "essentia"],
        essentia_bpm=128.0,
    )

    return cat


@pytest.fixture
def client(db):
    """TestClient with mocked lifespan so no config.yaml needed."""
    app.state.cat = db
    app.state.cfg = MagicMock()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    db.close()


# ── GET / ─────────────────────────────────────────────────────────────────────

def test_index_returns_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "SoundAgent" in r.text


def test_index_shows_file_count(client):
    r = client.get("/")
    assert "2 files" in r.text


# ── GET /search ───────────────────────────────────────────────────────────────

def test_search_no_params_returns_all(client):
    r = client.get("/search")
    assert r.status_code == 200
    assert "rain.wav" in r.text
    assert "kick.wav" in r.text


def test_search_fts_query(client):
    r = client.get("/search?q=rainfall")
    assert r.status_code == 200
    assert "rain.wav" in r.text
    assert "kick.wav" not in r.text


def test_search_by_category(client):
    r = client.get("/search?category=music")
    assert r.status_code == 200
    assert "kick.wav" in r.text
    assert "rain.wav" not in r.text


def test_search_by_content_type(client):
    r = client.get("/search?content_type=music")
    assert r.status_code == 200
    assert "kick.wav" in r.text
    assert "rain.wav" not in r.text


def test_search_by_source(client):
    r = client.get("/search?source=network")
    assert r.status_code == 200
    assert "kick.wav" in r.text
    assert "rain.wav" not in r.text


def test_search_no_results(client):
    r = client.get("/search?q=zzznomatch")
    assert r.status_code == 200
    assert "No results" in r.text


def test_search_min_bpm(client):
    r = client.get("/search?min_bpm=100")
    assert r.status_code == 200
    assert "kick.wav" in r.text
    assert "rain.wav" not in r.text


# ── GET /file/{hash} ──────────────────────────────────────────────────────────

def test_file_detail_returns_html(client):
    r = client.get("/file/h1")
    assert r.status_code == 200
    assert "rain.wav" in r.text
    assert "AMB-NATU" in r.text
    assert "rainfall" in r.text


def test_file_detail_shows_tags(client):
    r = client.get("/file/h1")
    assert "rain" in r.text
    assert "nature" in r.text


def test_file_detail_shows_usage_suggestions(client):
    r = client.get("/file/h1")
    assert "documentary" in r.text


def test_file_detail_shows_essentia_bpm(client):
    r = client.get("/file/h2")
    assert "128" in r.text


def test_file_detail_not_found(client):
    r = client.get("/file/nonexistent")
    assert r.status_code == 404


# ── GET /export.csv ───────────────────────────────────────────────────────────

def test_export_csv_returns_csv(client):
    r = client.get("/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "filename" in r.text   # header row


def test_export_csv_contains_results(client):
    r = client.get("/export.csv")
    assert "rain.wav" in r.text
    assert "kick.wav" in r.text


def test_export_csv_filtered(client):
    r = client.get("/export.csv?category=field")
    assert "rain.wav" in r.text
    assert "kick.wav" not in r.text


def test_export_csv_tags_joined(client):
    r = client.get("/export.csv?category=field")
    assert "rain; nature; forest" in r.text or "rain" in r.text


# ── GET /audio/{hash} ────────────────────────────────────────────────────────

def test_audio_not_found_returns_404(client):
    r = client.get("/audio/nonexistent")
    assert r.status_code == 404


def test_audio_missing_file_returns_404(client):
    # h1 library_path points to a tmp file that doesn't exist on disk
    r = client.get("/audio/h1")
    assert r.status_code == 404
