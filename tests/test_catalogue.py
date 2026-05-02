"""Tests for soundagent.catalogue — SQLite persistent catalogue."""

import json
import pytest
from pathlib import Path

from soundagent.catalogue import Catalogue, open_catalogue


@pytest.fixture
def cat(tmp_path):
    c = Catalogue(tmp_path / "test.db")
    yield c
    c.close()


def _insert_file(cat, hash="abc123", filename="test.wav", adapter="local",
                 library_path="/lib/sfx/test.wav", duration_s=3.0):
    cat.upsert_file(
        hash=hash,
        filename=filename,
        source_adapter=adapter,
        library_path=library_path,
        format="WAV",
        codec="pcm_s24le",
        duration_s=duration_s,
        sample_rate=48000,
        bit_depth=24,
        channels=2,
        file_size=288000,
    )


def _insert_enrichment(cat, hash="abc123", category="sfx", subcategory="impacts",
                       cat_id="SFX-IMPA", description="A heavy metal impact",
                       tags=None, bpm=None, key=None, confidence=0.95):
    cat.upsert_enrichment(
        hash=hash,
        category=category,
        subcategory=subcategory,
        cat_id=cat_id,
        description=description,
        tags=tags or ["metal", "impact", "heavy"],
        mood="tense",
        energy="high",
        bpm=bpm,
        key=key,
        confidence=confidence,
        low_confidence=confidence < 0.70,
    )


# ── Schema / open ─────────────────────────────────────────────────────────────

def test_schema_created(cat):
    tables = {row[0] for row in cat._con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"files", "enrichment", "ingest_log"}.issubset(tables)


def test_open_catalogue_creates_db(tmp_path):
    c = open_catalogue(tmp_path)
    assert (tmp_path / "soundlibrary.db").exists()
    c.close()


# ── is_known ──────────────────────────────────────────────────────────────────

def test_is_known_unknown_hash(cat):
    assert cat.is_known("deadbeef") is False


def test_is_known_file_without_library_path(cat):
    _insert_file(cat, library_path=None)
    assert cat.is_known("abc123") is False


def test_is_known_file_with_library_path(cat):
    _insert_file(cat)
    assert cat.is_known("abc123") is True


# ── upsert_file ───────────────────────────────────────────────────────────────

def test_upsert_file_inserts_row(cat):
    _insert_file(cat)
    row = cat._con.execute("SELECT * FROM files WHERE hash='abc123'").fetchone()
    assert row is not None
    assert row["filename"] == "test.wav"
    assert row["format"] == "WAV"
    assert row["duration_s"] == pytest.approx(3.0)


def test_upsert_file_updates_last_seen_on_conflict(cat):
    _insert_file(cat, hash="duphash")
    ts1 = cat._con.execute("SELECT last_seen FROM files WHERE hash='duphash'").fetchone()[0]
    import time; time.sleep(0.01)
    _insert_file(cat, hash="duphash")
    ts2 = cat._con.execute("SELECT last_seen FROM files WHERE hash='duphash'").fetchone()[0]
    assert ts2 >= ts1


def test_upsert_file_preserves_library_path_on_conflict(cat):
    _insert_file(cat, hash="h1", library_path="/some/path.wav")
    _insert_file(cat, hash="h1", library_path=None)   # should not overwrite
    row = cat._con.execute("SELECT library_path FROM files WHERE hash='h1'").fetchone()
    assert row[0] == "/some/path.wav"


def test_upsert_file_basehead_delivered_flag(cat):
    _insert_file(cat)
    row = cat._con.execute("SELECT basehead_delivered FROM files WHERE hash='abc123'").fetchone()
    assert row[0] == 0


# ── upsert_enrichment ─────────────────────────────────────────────────────────

def test_upsert_enrichment_stores_tags_as_json(cat):
    _insert_file(cat)
    _insert_enrichment(cat, tags=["rain", "water"])
    row = cat._con.execute("SELECT tags FROM enrichment WHERE hash='abc123'").fetchone()
    assert json.loads(row[0]) == ["rain", "water"]


def test_upsert_enrichment_updates_on_conflict(cat):
    _insert_file(cat)
    _insert_enrichment(cat, description="first")
    _insert_enrichment(cat, description="second")
    row = cat._con.execute("SELECT description FROM enrichment WHERE hash='abc123'").fetchone()
    assert row[0] == "second"


def test_upsert_enrichment_low_confidence_flag(cat):
    _insert_file(cat)
    _insert_enrichment(cat, confidence=0.50)
    row = cat._con.execute("SELECT low_confidence FROM enrichment WHERE hash='abc123'").fetchone()
    assert row[0] == 1


# ── log_event ─────────────────────────────────────────────────────────────────

def test_log_event_appends_rows(cat):
    cat.log_event("a.wav", "h1", "local", "delivered", destination="/lib/a.wav")
    cat.log_event("b.wav", "h2", "local", "error", error="boom")
    rows = cat._con.execute("SELECT * FROM ingest_log").fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == "delivered"
    assert rows[1]["status"] == "error"


def test_log_event_detail_is_json(cat):
    cat.log_event("a.wav", "h1", "local", "delivered", destination="/lib/a.wav")
    row = cat._con.execute("SELECT detail FROM ingest_log").fetchone()
    assert json.loads(row[0]) == {"destination": "/lib/a.wav"}


def test_log_event_no_detail_is_null(cat):
    cat.log_event("a.wav", "h1", "local", "staged")
    row = cat._con.execute("SELECT detail FROM ingest_log").fetchone()
    assert row[0] is None


# ── search ────────────────────────────────────────────────────────────────────

def _populate(cat):
    """Insert two files with enrichment for search tests."""
    _insert_file(cat, hash="h1", filename="rain.wav", duration_s=10.0)
    _insert_enrichment(cat, hash="h1", category="field", subcategory="nature",
                       cat_id="AMB-NATU", description="heavy rainfall on leaves",
                       tags=["rain", "nature"], confidence=0.92)

    _insert_file(cat, hash="h2", filename="kick.wav", duration_s=0.5,
                 adapter="network")
    _insert_enrichment(cat, hash="h2", category="sfx", subcategory="impacts",
                       cat_id="SFX-IMPA", description="punchy kick drum hit",
                       tags=["kick", "drum"], bpm=120.0, confidence=0.88)


def test_search_no_filters_returns_all(cat):
    _populate(cat)
    results = cat.search()
    assert len(results) == 2


def test_search_by_category(cat):
    _populate(cat)
    results = cat.search(category="field")
    assert len(results) == 1
    assert results[0]["hash"] == "h1"


def test_search_by_subcategory(cat):
    _populate(cat)
    results = cat.search(subcategory="impacts")
    assert len(results) == 1
    assert results[0]["hash"] == "h2"


def test_search_by_source(cat):
    _populate(cat)
    results = cat.search(source="network")
    assert len(results) == 1
    assert results[0]["filename"] == "kick.wav"


def test_search_min_duration(cat):
    _populate(cat)
    results = cat.search(min_duration=5.0)
    assert len(results) == 1
    assert results[0]["hash"] == "h1"


def test_search_max_duration(cat):
    _populate(cat)
    results = cat.search(max_duration=1.0)
    assert len(results) == 1
    assert results[0]["hash"] == "h2"


def test_search_bpm_range(cat):
    _populate(cat)
    results = cat.search(min_bpm=100.0, max_bpm=130.0)
    assert len(results) == 1
    assert results[0]["hash"] == "h2"


def test_search_tags_decoded_as_list(cat):
    _populate(cat)
    results = cat.search(category="field")
    assert isinstance(results[0]["tags"], list)
    assert "rain" in results[0]["tags"]


def test_search_fts_query(cat):
    _populate(cat)
    results = cat.search(query="rainfall")
    assert len(results) == 1
    assert results[0]["hash"] == "h1"


def test_search_fts_tag_match(cat):
    _populate(cat)
    results = cat.search(query="drum")
    assert len(results) == 1
    assert results[0]["hash"] == "h2"


def test_search_limit(cat):
    _populate(cat)
    results = cat.search(limit=1)
    assert len(results) == 1


# ── integrity_check ───────────────────────────────────────────────────────────

def test_integrity_check_passes(cat):
    assert cat.integrity_check() is True
