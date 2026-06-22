"""SQLite connection helper and schema bootstrap.

Single-user homelab app — uses the stdlib sqlite3 module with foreign keys
enabled and a tiny per-request connection pattern. No SQLAlchemy by spec.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(os.environ.get("GYM_DB_PATH", "data/gym.db")).resolve()

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS exercises (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    muscle_group TEXT NOT NULL CHECK(muscle_group IN ('Chest','Back','Legs','Shoulders','Biceps','Triceps','Core','Calves')),
    form_cues TEXT NOT NULL,
    media_slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d','now','localtime')),
    category TEXT NOT NULL CHECK(category IN ('Chest-and-Biceps','Back-and-Triceps','Legs','Shoulders','Custom')),
    start_time TEXT NOT NULL,
    end_time TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS set_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    exercise_id TEXT NOT NULL,
    set_index INTEGER NOT NULL,
    weight REAL NOT NULL,
    reps INTEGER NOT NULL,
    entry_status TEXT NOT NULL DEFAULT 'Completed' CHECK(entry_status IN ('Warm-up','Completed','Failure')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE RESTRICT,
    UNIQUE(session_id, exercise_id, set_index)
);

CREATE TABLE IF NOT EXISTS personal_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id TEXT NOT NULL,
    set_entry_id INTEGER NOT NULL,
    pr_date TEXT NOT NULL,
    est_1rm REAL NOT NULL,
    max_weight REAL NOT NULL,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE RESTRICT,
    FOREIGN KEY (set_entry_id) REFERENCES set_entries(id) ON DELETE CASCADE,
    UNIQUE(exercise_id, set_entry_id)
);

CREATE INDEX IF NOT EXISTS idx_set_entries_exercise_session ON set_entries(exercise_id, session_id);
CREATE INDEX IF NOT EXISTS idx_set_entries_date_analytics ON set_entries(exercise_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);

-- ===================================================================
-- Phase 0: Fitness Dashboard data foundation (ADDITIVE — do not modify
-- the tables above). These hold Garmin + Strava data pulled by app/sync.py.
-- All CREATE ... IF NOT EXISTS so a fresh clone boots cleanly and re-running
-- init_schema() is idempotent.
-- ===================================================================

-- Unified activities feed. `id` is source-prefixed, e.g. 'garmin:123',
-- 'strava:456', so the two sources never collide on the same PK.
CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    source TEXT,
    type TEXT,
    start_time TEXT,
    duration_s INTEGER,
    distance_m REAL,
    avg_hr INTEGER,
    elevation_m REAL,
    calories INTEGER,
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- One row per calendar day of Garmin wellness/training metrics.
CREATE TABLE IF NOT EXISTS daily_wellness (
    date TEXT PRIMARY KEY,
    vo2max_running REAL,
    resting_hr INTEGER,
    hrv_overnight REAL,
    body_battery_high INTEGER,
    body_battery_low INTEGER,
    stress_avg INTEGER,
    training_readiness INTEGER,
    training_load_acute REAL,
    training_load_chronic REAL,
    steps INTEGER,
    raw_json TEXT
);

-- One row per night of sleep (keyed on the wake-up calendar date).
CREATE TABLE IF NOT EXISTS sleep_nights (
    date TEXT PRIMARY KEY,
    duration_s INTEGER,
    deep_s INTEGER,
    light_s INTEGER,
    rem_s INTEGER,
    awake_s INTEGER,
    sleep_score INTEGER,
    raw_json TEXT
);

-- Nutrition is DEFERRED in garminconnect 0.3.6 (no food-diary getter); the
-- table exists so the schema is forward-compatible (design spec §9.6).
CREATE TABLE IF NOT EXISTS nutrition_days (
    date TEXT PRIMARY KEY,
    calories INTEGER,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    raw_json TEXT
);

-- Per-source sync bookkeeping: last run, the incremental watermark, and the
-- outcome so /api/sync/status and the next incremental run can read them.
CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    last_run_at TEXT,
    last_watermark TEXT,
    last_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities(start_time);
CREATE INDEX IF NOT EXISTS idx_activities_source_type ON activities(source, type);
"""


def get_connection() -> sqlite3.Connection:
    """Return a sqlite3.Connection with foreign keys enabled and row factory set."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a connection, committing on exit, closing always."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    """Create tables/indexes if not present. Idempotent."""
    with db_conn() as conn:
        conn.executescript(SCHEMA_SQL)


# Brzycki est-1RM helper used by the PR re-evaluation code.
def brzycki_est_1rm(weight: float, reps: int) -> float:
    """Brzycki 1RM estimate, with reps clamped to [1, 36]."""
    clamped = max(1, min(36, int(reps)))
    return float(weight) / (1.0278 - 0.0278 * clamped)
