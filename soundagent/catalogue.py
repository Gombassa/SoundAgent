"""
SQLite catalogue — persistent record of every file the agent has processed.

Schema
------
files        : one row per unique file (SHA-256 PK), technical + routing metadata
enrichment   : Claude enrichment result linked to files.hash (26 columns as of P7)
fts_search   : FTS5 virtual table over description+tags+usage_suggestions+notes
ingest_log   : append-only event log (mirrors the JSONL ingest.log in structured form)

Dedup
-----
On each tick, sha256 of every inbox file is checked against files.hash before
any processing starts. Known hashes are skipped entirely — this replaces the
within-tick-only dedup from P2.

Migration
---------
_migrate() adds columns to existing enrichment rows and rebuilds the FTS5 virtual
table when needed. FTS5 tables cannot be ALTERed; the rebuild drops triggers, drops
and recreates the table, repopulates from enrichment, and recreates triggers.
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
    hash                TEXT PRIMARY KEY REFERENCES files(hash),
    category            TEXT,
    subcategory         TEXT,
    cat_id              TEXT,
    description         TEXT,
    tags                TEXT,   -- JSON array
    mood                TEXT,
    energy              TEXT,
    bpm                 REAL,
    key                 TEXT,
    confidence          REAL,
    low_confidence      INTEGER,
    -- P7 audio analysis columns
    content_type        TEXT,
    usage_suggestions   TEXT,   -- JSON array
    notes               TEXT,
    language            TEXT,
    yamnet_classes      TEXT,   -- JSON array
    audioclip_matches   TEXT,   -- JSON array of {tag, category, score}
    audioclip_raw_scores TEXT,  -- JSON object {tag: score} for full vocabulary
    whisper_summary     TEXT,
    whisper_language    TEXT,
    essentia_bpm        REAL,
    essentia_key        TEXT,
    essentia_mood       TEXT,   -- JSON dict
    essentia_genre      TEXT,   -- JSON dict
    models_run          TEXT,   -- JSON array
    models_failed       TEXT,   -- JSON array
    librosa_bpm         REAL,
    librosa_key         TEXT,
    librosa_dynamic_complexity REAL
);

CREATE TABLE IF NOT EXISTS fingerprints (
    hash        TEXT PRIMARY KEY REFERENCES files(hash) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    duration_s  REAL,
    fpcalc_ver  TEXT,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS duplicates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    filename         TEXT NOT NULL,
    held_path        TEXT NOT NULL,
    match_type       TEXT NOT NULL,
    matched_hash     TEXT,
    matched_path     TEXT,
    matched_filename TEXT,
    similarity       REAL DEFAULT 1.0,
    detected_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    resolved         INTEGER DEFAULT 0
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
    usage_suggestions,
    notes,
    content='enrichment',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS enrichment_ai AFTER INSERT ON enrichment BEGIN
    INSERT INTO fts_search(rowid, hash, description, tags, usage_suggestions, notes)
    VALUES (new.rowid, new.hash, new.description, new.tags, new.usage_suggestions, new.notes);
END;

CREATE TRIGGER IF NOT EXISTS enrichment_ad AFTER DELETE ON enrichment BEGIN
    INSERT INTO fts_search(fts_search, rowid, hash, description, tags, usage_suggestions, notes)
    VALUES ('delete', old.rowid, old.hash, old.description, old.tags, old.usage_suggestions, old.notes);
END;

CREATE TRIGGER IF NOT EXISTS enrichment_au AFTER UPDATE ON enrichment BEGIN
    INSERT INTO fts_search(fts_search, rowid, hash, description, tags, usage_suggestions, notes)
    VALUES ('delete', old.rowid, old.hash, old.description, old.tags, old.usage_suggestions, old.notes);
    INSERT INTO fts_search(rowid, hash, description, tags, usage_suggestions, notes)
    VALUES (new.rowid, new.hash, new.description, new.tags, new.usage_suggestions, new.notes);
END;
"""

# Columns to add in migration (name, SQL type)
_NEW_ENRICHMENT_COLUMNS = [
    ("content_type",      "TEXT"),
    ("usage_suggestions", "TEXT"),
    ("notes",             "TEXT"),
    ("language",          "TEXT"),
    ("yamnet_classes",    "TEXT"),
    ("audioclip_matches",    "TEXT"),
    ("audioclip_raw_scores", "TEXT"),
    ("whisper_summary",   "TEXT"),
    ("whisper_language",  "TEXT"),
    ("essentia_bpm",      "REAL"),
    ("essentia_key",      "TEXT"),
    ("essentia_mood",     "TEXT"),
    ("essentia_genre",    "TEXT"),
    ("models_run",        "TEXT"),
    ("models_failed",     "TEXT"),
    ("librosa_bpm",       "REAL"),
    ("librosa_key",       "TEXT"),
    ("librosa_dynamic_complexity", "REAL"),
]

_FTS_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS enrichment_ai AFTER INSERT ON enrichment BEGIN
    INSERT INTO fts_search(rowid, hash, description, tags, usage_suggestions, notes)
    VALUES (new.rowid, new.hash, new.description, new.tags, new.usage_suggestions, new.notes);
END""",
    """CREATE TRIGGER IF NOT EXISTS enrichment_ad AFTER DELETE ON enrichment BEGIN
    INSERT INTO fts_search(fts_search, rowid, hash, description, tags, usage_suggestions, notes)
    VALUES ('delete', old.rowid, old.hash, old.description, old.tags, old.usage_suggestions, old.notes);
END""",
    """CREATE TRIGGER IF NOT EXISTS enrichment_au AFTER UPDATE ON enrichment BEGIN
    INSERT INTO fts_search(fts_search, rowid, hash, description, tags, usage_suggestions, notes)
    VALUES ('delete', old.rowid, old.hash, old.description, old.tags, old.usage_suggestions, old.notes);
    INSERT INTO fts_search(rowid, hash, description, tags, usage_suggestions, notes)
    VALUES (new.rowid, new.hash, new.description, new.tags, new.usage_suggestions, new.notes);
END""",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(con: sqlite3.Connection) -> None:
    """Add new columns to files/enrichment and rebuild FTS5 if needed."""
    existing_files = {row[1] for row in con.execute("PRAGMA table_info(files)").fetchall()}
    if "original_filename" not in existing_files:
        con.execute("ALTER TABLE files ADD COLUMN original_filename TEXT")
        log.debug("Migration: added files.original_filename")

    existing = {row[1] for row in con.execute("PRAGMA table_info(enrichment)").fetchall()}
    for col_name, col_type in _NEW_ENRICHMENT_COLUMNS:
        if col_name not in existing:
            con.execute(f"ALTER TABLE enrichment ADD COLUMN {col_name} {col_type}")
            log.debug(f"Migration: added enrichment.{col_name}")

    # Check if FTS includes usage_suggestions; rebuild if not
    fts_needs_rebuild = False
    try:
        con.execute("SELECT usage_suggestions FROM fts_search LIMIT 1")
    except sqlite3.OperationalError:
        fts_needs_rebuild = True

    if fts_needs_rebuild:
        log.info("Rebuilding FTS5 index to include usage_suggestions and notes")
        con.execute("DROP TRIGGER IF EXISTS enrichment_ai")
        con.execute("DROP TRIGGER IF EXISTS enrichment_ad")
        con.execute("DROP TRIGGER IF EXISTS enrichment_au")
        con.execute("DROP TABLE IF EXISTS fts_search")
        con.execute("""
            CREATE VIRTUAL TABLE fts_search USING fts5(
                hash UNINDEXED,
                description,
                tags,
                usage_suggestions,
                notes,
                content='enrichment',
                content_rowid='rowid'
            )
        """)
        con.execute("""
            INSERT INTO fts_search(rowid, hash, description, tags, usage_suggestions, notes)
            SELECT rowid, hash, description, tags, usage_suggestions, notes
            FROM enrichment
        """)
        for trigger_sql in _FTS_TRIGGERS:
            con.execute(trigger_sql)

    con.commit()


class Catalogue:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._con.executescript(_SCHEMA)
        self._con.commit()
        _migrate(self._con)

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
        original_filename: Optional[str] = None,
    ) -> None:
        now = _now()
        self._con.execute(
            """
            INSERT INTO files
              (hash, filename, source_adapter, library_path, format, codec,
               duration_s, sample_rate, bit_depth, channels, file_size,
               date_added, last_seen, basehead_delivered, original_filename)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hash) DO UPDATE SET
              last_seen          = excluded.last_seen,
              library_path       = COALESCE(excluded.library_path, library_path),
              basehead_delivered = excluded.basehead_delivered,
              original_filename  = COALESCE(original_filename, excluded.original_filename)
            """,
            (hash, filename, source_adapter, library_path, format, codec,
             duration_s, sample_rate, bit_depth, channels, file_size,
             now, now, int(basehead_delivered), original_filename),
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
        # P7 audio analysis fields (all optional for backward compat)
        content_type: Optional[str] = None,
        usage_suggestions: Optional[list[str]] = None,
        notes: Optional[str] = None,
        language: Optional[str] = None,
        yamnet_classes: Optional[list[str]] = None,
        audioclip_matches: Optional[list[dict]] = None,
        audioclip_raw_scores: Optional[dict] = None,
        whisper_summary: Optional[str] = None,
        whisper_language: Optional[str] = None,
        essentia_bpm: Optional[float] = None,
        essentia_key: Optional[str] = None,
        essentia_mood: Optional[dict] = None,
        essentia_genre: Optional[dict] = None,
        models_run: Optional[list[str]] = None,
        models_failed: Optional[list[str]] = None,
        librosa_bpm: Optional[float] = None,
        librosa_key: Optional[str] = None,
        librosa_dynamic_complexity: Optional[float] = None,
    ) -> None:
        def _j(x):
            return json.dumps(x) if x is not None else None

        self._con.execute(
            """
            INSERT INTO enrichment
              (hash, category, subcategory, cat_id, description, tags,
               mood, energy, bpm, key, confidence, low_confidence,
               content_type, usage_suggestions, notes, language,
               yamnet_classes, audioclip_matches, audioclip_raw_scores,
               whisper_summary, whisper_language,
               essentia_bpm, essentia_key, essentia_mood, essentia_genre,
               models_run, models_failed,
               librosa_bpm, librosa_key, librosa_dynamic_complexity)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hash) DO UPDATE SET
              category=excluded.category, subcategory=excluded.subcategory,
              cat_id=excluded.cat_id, description=excluded.description,
              tags=excluded.tags, mood=excluded.mood, energy=excluded.energy,
              bpm=excluded.bpm, key=excluded.key, confidence=excluded.confidence,
              low_confidence=excluded.low_confidence,
              content_type=excluded.content_type,
              usage_suggestions=excluded.usage_suggestions,
              notes=excluded.notes,
              language=excluded.language,
              yamnet_classes=excluded.yamnet_classes,
              audioclip_matches=excluded.audioclip_matches,
              audioclip_raw_scores=excluded.audioclip_raw_scores,
              whisper_summary=excluded.whisper_summary,
              whisper_language=excluded.whisper_language,
              essentia_bpm=excluded.essentia_bpm,
              essentia_key=excluded.essentia_key,
              essentia_mood=excluded.essentia_mood,
              essentia_genre=excluded.essentia_genre,
              models_run=excluded.models_run,
              models_failed=excluded.models_failed,
              librosa_bpm=excluded.librosa_bpm,
              librosa_key=excluded.librosa_key,
              librosa_dynamic_complexity=excluded.librosa_dynamic_complexity
            """,
            (hash, category, subcategory, cat_id, description,
             _j(tags), mood, energy, bpm, key,
             confidence, int(low_confidence),
             content_type, _j(usage_suggestions), notes, language,
             _j(yamnet_classes), _j(audioclip_matches), _j(audioclip_raw_scores),
             whisper_summary, whisper_language,
             essentia_bpm, essentia_key, _j(essentia_mood), _j(essentia_genre),
             _j(models_run), _j(models_failed),
             librosa_bpm, librosa_key, librosa_dynamic_complexity),
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

    # ── Fingerprints & duplicates ─────────────────────────────────────────────

    def get_file_by_hash(self, hash: str) -> Optional[dict]:
        """Return {hash, filename, library_path} for a catalogued file, or None."""
        row = self._con.execute(
            "SELECT hash, filename, library_path FROM files WHERE hash = ?",
            (hash,),
        ).fetchone()
        return dict(row) if row else None

    def store_fingerprint(
        self,
        hash: str,
        fingerprint: str,
        duration_s: Optional[float],
        fpcalc_ver: Optional[str],
    ) -> None:
        """INSERT OR REPLACE into fingerprints table."""
        self._con.execute(
            """
            INSERT OR REPLACE INTO fingerprints (hash, fingerprint, duration_s, fpcalc_ver)
            VALUES (?, ?, ?, ?)
            """,
            (hash, fingerprint, duration_s, fpcalc_ver),
        )
        self._con.commit()

    def find_fingerprint_match(
        self,
        fingerprint: str,
        threshold: float = 0.85,
    ) -> Optional[dict]:
        """
        Compare fingerprint against all stored fingerprints in Python.
        Returns {hash, path, filename, similarity} for the best match above
        threshold, or None. Logs a warning when the table exceeds 10,000 rows.
        """
        from soundagent.fingerprinter import similarity as fp_similarity

        rows = self._con.execute(
            """
            SELECT fp.hash, fp.fingerprint, f.library_path, f.filename
            FROM fingerprints fp
            JOIN files f ON f.hash = fp.hash
            WHERE f.library_path IS NOT NULL
            """
        ).fetchall()

        if len(rows) > 10_000:
            log.warning(
                f"fingerprints table has {len(rows)} rows — "
                "similarity search may be slow; consider a future indexing strategy"
            )

        best_sim = 0.0
        best: Optional[dict] = None
        for row in rows:
            sim = fp_similarity(fingerprint, row["fingerprint"])
            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best = {
                    "hash": row["hash"],
                    "path": row["library_path"],
                    "filename": row["filename"],
                    "similarity": sim,
                }
        return best

    def log_duplicate(
        self,
        filename: str,
        held_path: str,
        match_type: str,
        matched_hash: Optional[str],
        matched_path: Optional[str],
        matched_filename: Optional[str],
        similarity: float,
    ) -> None:
        """INSERT into duplicates table."""
        self._con.execute(
            """
            INSERT INTO duplicates
              (filename, held_path, match_type, matched_hash,
               matched_path, matched_filename, similarity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (filename, held_path, match_type, matched_hash,
             matched_path, matched_filename, similarity),
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
        content_type: Optional[str] = None,
        whisper_language: Optional[str] = None,
        min_confidence: Optional[float] = None,
        limit: int = 50,
    ) -> list[dict]:
        base_select = """
            SELECT f.*, e.category, e.subcategory, e.cat_id,
                   e.description, e.tags, e.mood, e.energy,
                   e.bpm, e.key, e.confidence, e.low_confidence,
                   e.content_type, e.usage_suggestions, e.notes, e.language,
                   e.yamnet_classes, e.audioclip_matches,
                   e.whisper_summary, e.whisper_language,
                   e.essentia_bpm, e.essentia_key,
                   e.models_run, e.models_failed
        """

        if query:
            sql = base_select + """
                FROM fts_search fs
                JOIN enrichment e ON e.hash = fs.hash
                JOIN files f ON f.hash = e.hash
                WHERE fts_search MATCH ?
            """
            params: list = [query]
        else:
            sql = base_select + """
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
        if content_type:
            sql += " AND e.content_type = ?"
            params.append(content_type)
        if whisper_language:
            sql += " AND e.whisper_language = ?"
            params.append(whisper_language)
        if min_confidence is not None:
            sql += " AND e.confidence >= ?"
            params.append(min_confidence)

        sql += f" LIMIT {int(limit)}"

        rows = self._con.execute(sql, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for json_col in ("tags", "usage_suggestions", "yamnet_classes",
                             "audioclip_matches", "models_run", "models_failed"):
                if d.get(json_col):
                    try:
                        d[json_col] = json.loads(d[json_col])
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
