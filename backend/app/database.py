"""SQLite connection helpers for the local MVP (WBS 0.3)."""

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
    """Create a local SQLite file without deleting existing data.

    Business tables are added in WBS 0.4. The PRAGMA initializes the file header
    without introducing a temporary business schema or changing its version.
    """
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        connection.execute(f"PRAGMA user_version = {version}")
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
