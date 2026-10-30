"""API startup/configuration failures without PostgreSQL or SQLite fallback."""

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import postgres
from app.dependencies import get_current_user_id
from app.main import create_app


@pytest.mark.parametrize("url", [None, "sqlite:///must-not-create.sqlite3", "invalid-private-url"])
def test_missing_or_invalid_postgres_config_keeps_only_liveness_available(tmp_path, monkeypatch, url):
    if url is None:
        monkeypatch.delenv("BAKURAKU_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("BAKURAKU_DATABASE_URL", url)
    legacy = tmp_path / "legacy.sqlite3"
    legacy.write_bytes(b"existing SQLite file must be preserved")
    monkeypatch.setenv("BAKURAKU_DB_PATH", str(legacy))
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        for method, path in [
            ("get", "/api/health/db"), ("get", "/api/attendance/status"),
            ("get", "/api/attendance/history"), ("post", "/api/attendance/clock-in"),
            ("post", "/api/attendance/clock-out"),
            ("post", "/api/attendance/cancel"),
            ("get", "/api/attendance/overdue"),
            ("post", "/api/attendance/overdue/confirm"),
            ("get", "/api/attendance/records"),
            ("get", "/api/attendance/records/1"),
            ("get", "/api/attendance/records/1/audit-logs"),
            ("patch", "/api/attendance/records/1"),
        ]:
            response = getattr(client, method)(path)
            assert response.status_code == 503
            assert response.json() == {"detail": "Database unavailable"}
        assert not (tmp_path / "must-not-create.sqlite3").exists()
    assert legacy.read_bytes() == b"existing SQLite file must be preserved"


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/health/db", None),
    ("GET", "/api/attendance/status", None),
    ("GET", "/api/attendance/history", None),
    ("POST", "/api/attendance/clock-in", None),
    ("POST", "/api/attendance/clock-out", None),
    ("POST", "/api/attendance/cancel", None),
    ("GET", "/api/attendance/overdue", None),
    ("POST", "/api/attendance/overdue/confirm", {"choice": "still_working"}),
    ("GET", "/api/attendance/records", None),
    ("GET", "/api/attendance/records/1", None),
    ("GET", "/api/attendance/records/1/audit-logs", None),
    ("PATCH", "/api/attendance/records/1", {
        "clock_in_at": "2026-10-29T22:00:00+09:00",
        "clock_out_at": "2026-10-30T07:00:00+09:00",
        "expected_operation_id": 1,
        "change_reason": "退勤打刻を忘れたため",
    }),
])
def test_database_failure_is_sanitized_and_liveness_stays_independent(
    monkeypatch, method, path, payload,
):
    monkeypatch.setenv("BAKURAKU_DATABASE_URL", "postgresql+psycopg://localhost/unused")

    @contextmanager
    def unavailable(engine):
        raise OperationalError("SELECT private", {}, Exception("private connection details"))
        yield  # contextmanager protocol; no database connection is attempted

    monkeypatch.setattr(postgres, "session_scope", unavailable)
    application = create_app()
    # Reach each service's DB access, rather than failing in demo-user lookup.
    application.dependency_overrides[get_current_user_id] = lambda: 1
    with TestClient(application) as client:
        assert client.get("/api/health").status_code == 200
        response = client.request(method, path, json=payload)
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
        assert client.get("/api/health").json() == {"status": "ok"}


def test_openapi_declares_integer_ids_and_no_client_supplied_dependencies(monkeypatch):
    monkeypatch.delenv("BAKURAKU_DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if path.startswith("/api/attendance/"):
            for method, operation in methods.items():
                parameters = operation.get("parameters", [])
                if "{record_id}" in path:
                    assert [(p["in"], p["name"]) for p in parameters] == [("path", "record_id")]
                else:
                    assert not parameters
                if path == "/api/attendance/overdue/confirm":
                    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
                    assert body_schema == {
                        "$ref": "#/components/schemas/OverdueConfirmationRequest",
                    }
                elif path == "/api/attendance/records/{record_id}" and method == "patch":
                    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
                    assert body_schema == {"$ref": "#/components/schemas/AttendanceCorrectionRequest"}
                else:
                    assert "requestBody" not in operation
    properties = schema["components"]["schemas"]["AttendanceRecord"]["properties"]
    assert properties["user_id"]["type"] == "integer"


def test_init_db_requires_postgres_and_does_not_create_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("BAKURAKU_DATABASE_URL", raising=False)
    legacy = tmp_path / "legacy.sqlite3"
    legacy.write_bytes(b"preserve me")
    monkeypatch.setenv("BAKURAKU_DB_PATH", str(legacy))
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "dev.py"), "init-db"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert "BAKURAKU_DATABASE_URL must be set" in result.stderr
    assert legacy.read_bytes() == b"preserve me"
