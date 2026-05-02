"""
SQLite catalogue — persistent record of every file the agent has processed.

Schema
------
files        : one row per unique file (SHA-256 PK), technical + routing metadata
enrichment   : Claude enrichment result linked to files.hash
fts_search   : FTS5 virtual table over description + tags for full-text search
ingest_log   : append-only event log (mirrors the JSONL ingest.log in structured form)

Dedup
-----
On each tick, sha256 of every inbox file is checked against files.hash before
any processing starts. Known hashes are skipped entirely — this replaces the
within-tick-only dedup from P2.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("soundagent.catalogue")

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    hash            TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    source_adapter  TEXT NOT NULL,
    library_path    TEXT,
    format          TEXT,
    codec           TEXT,
    duration_s      REAL,
    sample_rate     INTEGER,
    bit_depth       INTEGER,
    channels        INTEGER,
    file_size       INTEGER,
    date_added      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    basehead_delivered INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS enrichment (
    hash            TEXT PRIMARY KEY REFERENCES files(hash),
    category        TEXT,
    subcategory     TEXT,
    cat_id          TEXT,
    description     TEXT,
    tags            TEXT,   -- JSON array
    mood            TEXT,
    energy          TEXT,
    bpm             REAL,
    key             TEXT,
    confidence      REAL,
    low_confidence  INTEGER
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    filename        TEXT NOT NULL,
    hash            TEXT NOT NULL,
    source          TEXT NOT NULL,
    status          TEXT NOT NULL,
    detail          TEXT        -- JSON blob for extra fields
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_search USING fts5(
    hash UNINDEXED,
    description,
    tags,
    content='enrichment',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS enrichment_ai AFTER INSERT ON enrichment BEGIN
    INSERT INTO fts_search(rowid, hash, description, tags)
    VALUES (new.rowid, new.hash, new.description, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS enrichment_ad AFTER DELETE ON enrichment BEGIN
    INSERT INTO fts_search(fts_search, rowid, hash, description, tags)
    VALUES ('delete', old.rowid, old.hash, old.description, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS enrichment_au AFTER UPDATE ON enrichment BEGIN
    INSERT INTO fts_search(fts_search, rowid, hash, description, tags)
    VALUES ('delete', old.rowid, old.hash, old.description, old.tags);
    INSERT INTO fts_search(rowid, hash, description, tags)
    VALUES (new.rowid, new.hash, new.description, new.tags);
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Catalogue:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._con.executescript(_SCHEMA)
        self._con.commit()

    def close(self) -> None:
        self._con.close()

    # ── Dedup ─────────────────────────────────────────────────────────────────

    def is_known(self, file_hash: str) -> bool:
        """Return True if this hash has already been fully processed."""
        row = self._con.execute(
            "SELECT 1 FROM files WHERE hash = ? AND library_path IS NOT NULL",
            (file_hash,),
        ).fetchone()
        return row is not None

    # ── Upsert ────────────────────────────────────────────────────────────────

    def upsert_file(
        self,
        hash: str,
        filename: str,
        source_adapter: str,
        library_path: Optional[str] = None,
        format: str = "",
        codec: str = "",
        duration_s: float = 0.0,
        sample_rate: int = 0,
        bit_depth: Optional[int] = None,
        channels: int = 0,
        file_size: int = 0,
        basehead_delivered: bool = False,
    ) -> None:
        now = _now()
        self._con.execute(
            """
            INSERT INTO files
              (hash, filename, source_adapter, library_path, format, codec,
               duration_s, sample_rate, bit_depth, channels, file_size,
               date_added, last_seen, basehead_delivered)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hash) DO UPDATE SET
              last_seen          = excluded.last_seen,
              library_path       = COALESCE(excluded.library_path, library_path),
              basehead_delivered = excluded.basehead_delivered
            """,
            (hash, filename, source_adapter, library_path, format, codec,
             duration_s, sample_rate, bit_depth, channels, file_size,
             now, now, int(basehead_delivered)),
        )
        self._con.commit()

    def upsert_enrichment(
        self,
        hash: str,
        category: str,
        subcategory: str,
        cat_id: str,
        description: str,
        tags: list[str],
        mood: str,
        energy: str,
        bpm: Optional[float],
        key: Optional[str],
        confidence: float,
        low_confidence: bool,
    ) -> None:
        self._con.execute(
            """
            INSERT INTO enrichment
              (hash, category, subcategory, cat_id, description, tags,
               mood, energy, bpm, key, confidence, low_confidence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hash) DO UPDATE SET
              category=excluded.category, subcategory=excluded.subcategory,
              cat_id=excluded.cat_id, description=excluded.description,
              tags=excluded.tags, mood=excluded.mood, energy=excluded.energy,
              bpm=excluded.bpm, key=excluded.key, confidence=excluded.confidence,
              low_confidence=excluded.low_confidence
            """,
            (hash, category, subcategory, cat_id, description,
             json.dumps(tags), mood, energy, bpm, key,
             confidence, int(low_confidence)),
        )
        self._con.commit()

    def log_event(
        self, filename: str, hash: str, source: str, status: str, **detail
    ) -> None:
        self._con.execute(
            "INSERT INTO ingest_log (ts, filename, hash, source, status, detail) VALUES (?,?,?,?,?,?)",
            (_now(), filename, hash, source, status,
             json.dumps(detail) if detail else None),
        )
        self._con.commit()

    # ── Query ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        min_bpm: Optional[float] = None,
        max_bpm: Optional[float] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        if query:
            # FTS search — join back to files + enrichment
            sql = """
                SELECT f.*, e.category, e.subcategory, e.cat_id,
                       e.description, e.tags, e.mood, e.energy,
                       e.bpm, e.key, e.confidence
                FROM fts_search fs
                JOIN enrichment e ON e.hash = fs.hash
                JOIN files f ON f.hash = e.hash
                WHERE fts_search MATCH ?
            """
            params: list = [query]
        else:
            sql = """
                SELECT f.*, e.category, e.subcategory, e.cat_id,
                       e.description, e.tags, e.mood, e.energy,
                       e.bpm, e.key, e.confidence
                FROM files f
                LEFT JOIN enrichment e ON e.hash = f.hash
                WHERE 1=1
            """
            params = []

        if category:
            sql += " AND e.category = ?"
            params.append(category.lower())
        if subcategory:
            sql += " AND e.subcategory = ?"
            params.append(subcategory.lower())
        if min_duration is not None:
            sql += " AND f.duration_s >= ?"
            params.append(min_duration)
        if max_duration is not None:
            sql += " AND f.duration_s <= ?"
            params.append(max_duration)
        if min_bpm is not None:
            sql += " AND e.bpm >= ?"
            params.append(min_bpm)
        if max_bpm is not None:
            sql += " AND e.bpm <= ?"
            params.append(max_bpm)
        if source:
            sql += " AND f.source_adapter = ?"
            params.append(source)

        sql += f" LIMIT {int(limit)}"

        rows = self._con.execute(sql, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("tags"):
                try:
                    d["tags"] = json.loads(d["tags"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    # ── Integrity check ───────────────────────────────────────────────────────

    def integrity_check(self) -> bool:
        result = self._con.execute("PRAGMA integrity_check").fetchone()
        ok = result[0] == "ok"
        if not ok:
            log.error(f"DB integrity check failed: {result[0]}")
        return ok


def open_catalogue(library_root: Path) -> Catalogue:
    db_path = library_root / "soundlibrary.db"
    return Catalogue(db_path)
