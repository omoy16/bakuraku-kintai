"""Configuration and offline migration checks; no PostgreSQL server needed."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.postgres import create_db_engine, get_database_url

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = ROOT / "backend" / "alembic.ini"


def test_postgres_url_must_be_explicit(monkeypatch):
    monkeypatch.delenv("BAKURAKU_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="BAKURAKU_DATABASE_URL must be set"):
        get_database_url()


@pytest.mark.parametrize("value", [
    "sqlite:///test.db", "postgresql+asyncpg://localhost/test", "invalid-secret-url",
])
def test_invalid_urls_are_rejected_without_exposing_the_value(value):
    with pytest.raises(ValueError) as error:
        get_database_url(value)
    assert value not in str(error.value)


def test_engine_is_lazy_and_handles_url_escaped_passwords():
    engine = create_db_engine("postgresql://local:p%40ss%25word@localhost/example")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.password == "p@ss%word"
        assert engine.hide_parameters
    finally:
        engine.dispose()


def test_offline_sql_from_another_directory(tmp_path):
    env = {**os.environ, "BAKURAKU_DATABASE_URL": "postgresql+psycopg://localhost/offline"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG),
         "upgrade", "head", "--sql"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in result.stdout
    assert "CREATE TABLE attendance_audit_logs" in result.stdout
    assert "EXCLUDE USING gist" in result.stdout
    assert "GENERATED ALWAYS AS IDENTITY" in result.stdout
    assert "change_reason TEXT" in result.stdout


def test_revision_history_does_not_require_a_database(tmp_path):
    env = dict(os.environ)
    env.pop("BAKURAKU_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "heads"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "0001_attendance_schema (head)" in result.stdout
