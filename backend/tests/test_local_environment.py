"""Smoke tests for the local API, database lifecycle, and command entry point."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import BACKEND_DIR, connect_db, get_db_path, init_db
from app.main import app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "data" / "test.sqlite3"
    monkeypatch.setenv("BAKURAKU_DB_PATH", str(path))
    return path


def test_api_liveness_does_not_require_db(db_path):
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not db_path.exists()


def test_database_health_requires_initialization(db_path):
    with TestClient(app) as client:
        response = client.get("/api/health/db")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
        assert not db_path.exists()
        init_db()
        response = client.get("/api/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "sqlite"}


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


def test_init_db_command_from_another_directory(db_path, tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "dev.py"), "init-db"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert db_path.is_file()
    assert "SQLite ready:" in result.stdout


def test_database_health_rejects_corrupt_file(db_path):
    db_path.parent.mkdir(parents=True)
    db_path.write_text("not a SQLite database", encoding="utf-8")
    with TestClient(app) as client:
        response = client.get("/api/health/db")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
