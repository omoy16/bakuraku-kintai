"""Regression tests for request DI and service/HTTP boundaries on PostgreSQL."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import attendance_service
from app.dependencies import get_clock, get_current_user_id
from app.models import AttendanceRecord as Record
from app.postgres import session_scope

pytestmark = pytest.mark.postgres


def test_identity_is_resolved_per_request_for_all_operations(client, demo_id, other_id):
    current = {"user_id": demo_id}
    client.app.dependency_overrides[get_current_user_id] = lambda: current["user_id"]
    first = client.post("/api/attendance/clock-in").json()
    assert first["user_id"] == demo_id
    current["user_id"] = other_id
    assert client.get("/api/attendance/status").json() == {
        "user_id": other_id, "status": "not_working", "active_record": None,
    }
    assert client.get("/api/attendance/history").json() == []
    assert client.post("/api/attendance/clock-out").status_code == 409
    second = client.post("/api/attendance/clock-in").json()
    assert second["user_id"] == other_id
    assert client.post("/api/attendance/clock-out").status_code == 200
    assert [r["id"] for r in client.get("/api/attendance/history").json()] == [second["id"]]
    current["user_id"] = demo_id
    assert client.get("/api/attendance/status").json()["active_record"] == first
    assert client.post("/api/attendance/clock-out").json()["id"] == first["id"]
    assert [r["id"] for r in client.get("/api/attendance/history").json()] == [first["id"]]


def test_clock_dependency_is_resolved_for_each_request(client):
    current = {"time": datetime(2026, 10, 29, tzinfo=timezone.utc)}
    client.app.dependency_overrides[get_clock] = lambda: lambda: current["time"]
    start = client.post("/api/attendance/clock-in").json()
    current["time"] = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)
    end = client.post("/api/attendance/clock-out").json()
    assert datetime.fromisoformat(start["clock_in_at"]).hour == 0
    assert datetime.fromisoformat(end["clock_out_at"]).hour == 8


def test_query_inputs_cannot_override_dependencies(client, demo_id):
    client.post("/api/attendance/clock-in")
    query = {"user_id": 999, "engine": "fake", "clock": "fake"}
    status = client.get("/api/attendance/status", params=query)
    history = client.get("/api/attendance/history", params=query)
    assert status.json()["user_id"] == demo_id
    assert {r["user_id"] for r in history.json()} == {demo_id}
    assert client.post("/api/attendance/clock-out", params=query).status_code == 200


def test_programming_error_is_500_and_does_not_commit_partial_writes(client, api_db, monkeypatch):
    def broken(row):
        raise ValueError("private unexpected programming error")

    monkeypatch.setattr(attendance_service, "as_record", broken)
    with TestClient(client.app, raise_server_exceptions=False) as non_raising:
        response = non_raising.post("/api/attendance/clock-in")
    assert response.status_code == 500
    assert "unexpected programming error" not in response.text
    with session_scope(api_db) as session:
        assert session.scalar(select(func.count()).select_from(Record)) == 0


def test_health_is_independent_of_attendance_dependencies(client):
    def unavailable():
        raise AssertionError("attendance dependency must not run")

    client.app.dependency_overrides[get_current_user_id] = unavailable
    client.app.dependency_overrides[get_clock] = unavailable
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.get("/api/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "postgresql"}
