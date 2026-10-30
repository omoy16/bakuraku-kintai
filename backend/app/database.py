"""Legacy SQLite PoC helpers, retained for existing files; the API uses postgres.py."""

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

BACKEND_DIR = Path(__file__).resolve().parents[1]


def get_db_path() -> Path:
    """Resolve relative paths from backend/, independent of the working directory."""
    path = Path(os.environ.get("BAKURAKU_DB_PATH", "data/bakuraku.sqlite3")).expanduser()
    return (path if path.is_absolute() else BACKEND_DIR / path).resolve()


def init_db() -> Path:
    """Create the MVP tables and indexes without deleting existing data."""
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                clock_in_at TEXT NOT NULL,
                clock_out_at TEXT,
                CHECK (clock_out_at IS NULL OR clock_out_at >= clock_in_at)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_attendance_per_user
                ON attendance_records (user_id) WHERE clock_out_at IS NULL;
        """)
        connection.commit()
    return path


@contextmanager
def connect_db() -> Iterator[sqlite3.Connection]:
    """Open an initialized DB; commit on success, rollback on failure, then close."""
    # mode=rw avoids silently creating a different DB when configuration is wrong.
    uri = get_db_path().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
