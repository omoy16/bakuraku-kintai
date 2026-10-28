"""Verify request dependencies, unchanged contracts, and error/transaction boundaries."""

import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import attendance_service, database
from app.dependencies import get_clock, get_current_user_id
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BAKURAKU_DB_PATH", str(tmp_path / "api.sqlite3"))
    database.init_db()
    saved = app.dependency_overrides.copy()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def test_identity_is_resolved_per_request_for_all_attendance_operations(client):
    current = {"user_id": "user-A"}
    app.dependency_overrides[get_current_user_id] = lambda: current["user_id"]
    first = client.post("/api/attendance/clock-in").json()
    assert first["user_id"] == "user-A"

    current["user_id"] = "user-B"
    assert client.get("/api/attendance/status").json() == {
        "user_id": "user-B", "status": "not_working", "active_record": None,
    }
    assert client.get("/api/attendance/history").json() == []
    assert client.post("/api/attendance/clock-out").status_code == 409
    second = client.post("/api/attendance/clock-in").json()
    assert second["user_id"] == "user-B"
    assert second["id"] != first["id"]
    assert client.post("/api/attendance/clock-out").status_code == 200
    assert [r["id"] for r in client.get("/api/attendance/history").json()] == [second["id"]]

    current["user_id"] = "user-A"
    assert client.get("/api/attendance/status").json()["active_record"] == first
    assert client.post("/api/attendance/clock-out").json()["id"] == first["id"]
    assert [r["id"] for r in client.get("/api/attendance/history").json()] == [first["id"]]
    with database.connect_db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0] == 2


def test_client_cannot_supply_identity_or_clock_through_query_or_body(client):
    now = datetime(2026, 10, 29, 1, 2, 3, tzinfo=timezone.utc)
    app.dependency_overrides[get_clock] = lambda: lambda: now
    fake = {"user_id": "someone-else", "clock": "fake", "clock_in_at": "2000-01-01T00:00:00Z"}
    response = client.post("/api/attendance/clock-in", params=fake, json=fake)
    assert response.status_code == 201
    record = response.json()
    assert record["user_id"] == "demo-user"
    assert datetime.fromisoformat(record["clock_in_at"]) == now
    assert client.get("/api/attendance/status", params=fake).json()["active_record"] == record
    assert client.get("/api/attendance/history", params=fake).json() == [record]
    finished = client.post("/api/attendance/clock-out", params=fake, json=fake)
    assert finished.status_code == 200
    assert finished.json()["id"] == record["id"]
    assert datetime.fromisoformat(finished.json()["clock_out_at"]) == now


def test_clock_runs_after_write_lock_and_only_for_valid_transitions(client):
    calls = []
    now = datetime(2026, 10, 29, 1, 2, 3, tzinfo=timezone.utc)

    def clock():
        # Another writer must already be blocked when the service reads the clock.
        with closing(sqlite3.connect(database.get_db_path(), timeout=0)) as other:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        calls.append(now)
        return now

    app.dependency_overrides[get_clock] = lambda: clock
    assert client.post("/api/attendance/clock-out").status_code == 409
    assert calls == []
    assert client.post("/api/attendance/clock-in").status_code == 201
    assert calls == [now]
    assert client.post("/api/attendance/clock-in").status_code == 409
    assert calls == [now]
    assert client.post("/api/attendance/clock-out").status_code == 200
    assert calls == [now, now]
    assert client.post("/api/attendance/clock-out").status_code == 409
    assert calls == [now, now]


def test_commit_failure_is_503_before_response_and_write_is_rolled_back(client, monkeypatch):
    original = database.connect_db

    @contextmanager
    def failed_commit():
        with original() as connection:
            yield connection
            # Fail after the insert/response model, inside the transaction scope.
            raise sqlite3.OperationalError("private database path /secret/example")

    monkeypatch.setattr(database, "connect_db", failed_commit)
    response = client.post("/api/attendance/clock-in")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    with original() as connection:
        assert connection.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0] == 0


def test_programming_error_is_not_misreported_as_database_outage(client, monkeypatch):
    def broken_conversion(row):
        raise ValueError("an unexpected programming error")

    monkeypatch.setattr(attendance_service, "as_record", broken_conversion)
    with TestClient(app, raise_server_exceptions=False) as non_raising:
        response = non_raising.post("/api/attendance/clock-in")
    assert response.status_code == 500
    assert "unexpected programming error" not in response.text
    with database.connect_db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0] == 0


@pytest.mark.parametrize("path", ["/api/attendance/status", "/api/health/db"])
def test_invalid_db_path_is_a_sanitized_503(client, monkeypatch, path):
    def invalid_path():
        raise ValueError("invalid database configuration /private/example")

    monkeypatch.setattr(database, "get_db_path", invalid_path)
    response = client.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_liveness_does_not_resolve_identity_or_clock(client, monkeypatch):
    def unavailable():
        raise AssertionError("attendance dependency must not run")

    app.dependency_overrides[get_current_user_id] = unavailable
    app.dependency_overrides[get_clock] = unavailable
    assert client.get("/api/health/db").json() == {"status": "ok", "database": "sqlite"}
    monkeypatch.setattr(database, "get_db_path", unavailable)
    assert client.get("/api/health").json() == {"status": "ok"}


def test_openapi_keeps_internal_dependencies_out_of_public_inputs(client):
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if path.startswith("/api/attendance/"):
            for operation in methods.values():
                assert not operation.get("parameters")
                assert "requestBody" not in operation
    assert schema["components"]["schemas"]["AttendanceRecord"]["required"] == [
        "id", "user_id", "clock_in_at", "clock_out_at",
    ]
