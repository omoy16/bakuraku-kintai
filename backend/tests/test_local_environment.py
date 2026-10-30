"""Legacy SQLite helpers preserve existing files; the API no longer uses SQLite."""

import sqlite3

import pytest

from app.database import BACKEND_DIR, connect_db, get_db_path, init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "data" / "test.sqlite3"
    monkeypatch.setenv("BAKURAKU_DB_PATH", str(path))
    return path


def test_initialization_preserves_existing_data_and_version(db_path):
    assert init_db() == db_path
    with connect_db() as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES (?)", ("demo",))
        connection.execute("PRAGMA user_version = 7")
    init_db()
    with connect_db() as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "demo"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_connection_rolls_back_and_closes(db_path):
    init_db()
    with connect_db() as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
    with pytest.raises(RuntimeError):
        with connect_db() as failed_connection:
            failed_connection.execute("INSERT INTO sample VALUES (?)", ("discard",))
            raise RuntimeError("simulate failed operation")
    with pytest.raises(sqlite3.ProgrammingError):
        failed_connection.execute("SELECT 1")
    with connect_db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0


def test_relative_path_is_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("BAKURAKU_DB_PATH", "data/custom.sqlite3")
    monkeypatch.chdir(tmp_path)
    assert get_db_path() == BACKEND_DIR / "data" / "custom.sqlite3"
