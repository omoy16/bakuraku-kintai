"""Verify punch transitions, persistence, overnight shifts, and concurrent writes."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import connect_db, init_db
from app.dependencies import get_clock
from app.main import app


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "attendance.sqlite3"
    monkeypatch.setenv("BAKURAKU_DB_PATH", str(path))
    init_db()
    return path


@pytest.fixture
def client(database):
    with TestClient(app) as client:
        yield client


def set_time(monkeypatch, value):
    now = datetime.fromisoformat(value)
    monkeypatch.setitem(app.dependency_overrides, get_clock, lambda: lambda: now)
    return now


def test_punch_cycle_persists_and_can_start_another_shift(client, monkeypatch):
    assert client.get("/api/attendance/status").json() == {
        "user_id": "demo-user", "status": "not_working", "active_record": None,
    }
    start = set_time(monkeypatch, "2026-10-23T00:00:00+00:00")
    response = client.post("/api/attendance/clock-in")
    assert response.status_code == 201
    record = response.json()
    assert record["user_id"] == "demo-user"
    assert datetime.fromisoformat(record["clock_in_at"]) == start
    assert record["clock_out_at"] is None
    status = client.get("/api/attendance/status").json()
    assert status["status"] == "working"
    assert status["active_record"] == record

    # A fresh client and another initialization must retain the active shift.
    init_db()
    with TestClient(app) as other_client:
        assert other_client.get("/api/attendance/status").json() == status
    end = set_time(monkeypatch, "2026-10-23T09:00:00+00:00")
    response = client.post("/api/attendance/clock-out")
    assert response.status_code == 200
    finished = response.json()
    assert finished["id"] == record["id"]
    assert datetime.fromisoformat(finished["clock_out_at"]) == end
    assert client.get("/api/attendance/status").json()["status"] == "not_working"
    assert client.post("/api/attendance/clock-in").status_code == 201
    with connect_db() as connection:
        rows = connection.execute("SELECT * FROM attendance_records ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["clock_out_at"] is not None
    assert rows[1]["clock_out_at"] is None


def test_history_is_empty_before_first_punch(client):
    response = client.get("/api/attendance/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_returns_only_demo_user_newest_first(client, monkeypatch):
    first_start = set_time(monkeypatch, "2026-10-21T00:00:00+00:00")
    first = client.post("/api/attendance/clock-in").json()
    first_end = set_time(monkeypatch, "2026-10-21T08:00:00+00:00")
    client.post("/api/attendance/clock-out")

    with connect_db() as connection:
        connection.execute(
            """INSERT INTO attendance_records (user_id, clock_in_at, clock_out_at)
               VALUES (?, ?, ?)""",
            (
                "another-user",
                "2026-10-22T00:00:00.000000+00:00",
                "2026-10-22T08:00:00.000000+00:00",
            ),
        )

    second_start = set_time(monkeypatch, "2026-10-23T00:00:00+00:00")
    second = client.post("/api/attendance/clock-in").json()

    response = client.get("/api/attendance/history")
    assert response.status_code == 200
    assert [record["id"] for record in response.json()] == [second["id"], first["id"]]
    assert datetime.fromisoformat(response.json()[0]["clock_in_at"]) == second_start
    assert response.json()[0]["clock_out_at"] is None
    assert datetime.fromisoformat(response.json()[1]["clock_in_at"]) == first_start
    assert datetime.fromisoformat(response.json()[1]["clock_out_at"]) == first_end
    assert {record["user_id"] for record in response.json()} == {"demo-user"}


def test_invalid_transitions_do_not_change_records(client):
    assert client.post("/api/attendance/clock-out").status_code == 409
    original = client.post("/api/attendance/clock-in").json()
    response = client.post("/api/attendance/clock-in")
    assert response.status_code == 409
    assert response.json() == {"detail": "Already working"}
    assert client.get("/api/attendance/status").json()["active_record"] == original
    finished = client.post("/api/attendance/clock-out").json()
    response = client.post("/api/attendance/clock-out")
    assert response.status_code == 409
    assert response.json() == {"detail": "Not working"}
    with connect_db() as connection:
        rows = connection.execute("SELECT * FROM attendance_records").fetchall()
    assert len(rows) == 1
    assert datetime.fromisoformat(rows[0]["clock_out_at"]) == datetime.fromisoformat(finished["clock_out_at"])


@pytest.mark.parametrize("start,end", [
    ("2026-10-23T14:30:00+00:00", "2026-10-23T16:00:00+00:00"),  # JST midnight
    ("2026-10-23T23:30:00+00:00", "2026-10-24T01:00:00+00:00"),  # UTC midnight
    ("2026-10-23T00:00:00+00:00", "2026-10-25T00:00:00+00:00"),  # no automatic clock-out
])
def test_overnight_and_long_running_shifts(client, monkeypatch, start, end):
    set_time(monkeypatch, start)
    original = client.post("/api/attendance/clock-in").json()
    set_time(monkeypatch, end)
    status = client.get("/api/attendance/status").json()
    assert status["status"] == "working"
    assert status["active_record"] == original
    assert client.post("/api/attendance/clock-in").status_code == 409
    response = client.post("/api/attendance/clock-out")
    assert response.status_code == 200
    assert response.json()["id"] == original["id"]
    assert datetime.fromisoformat(response.json()["clock_out_at"]) == datetime.fromisoformat(end)


@pytest.mark.parametrize("action,success", [("clock-in", 201), ("clock-out", 200)])
def test_concurrent_punches_allow_one_success(client, action, success):
    if action == "clock-out":
        assert client.post("/api/attendance/clock-in").status_code == 201
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post(f"/api/attendance/{action}"), range(2)))
    assert sorted(response.status_code for response in responses) == sorted([success, 409])
    with connect_db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0] == 1


def test_database_unique_index_prevents_two_active_shifts(database):
    with connect_db() as connection:
        connection.execute("INSERT INTO attendance_records (user_id, clock_in_at) VALUES (?, ?)",
                           ("demo-user", "2026-10-23T00:00:00.000000+00:00"))
    with pytest.raises(sqlite3.IntegrityError):
        with connect_db() as connection:
            connection.execute("INSERT INTO attendance_records (user_id, clock_in_at) VALUES (?, ?)",
                               ("demo-user", "2026-10-23T01:00:00.000000+00:00"))


def test_user_and_timestamps_are_server_controlled(client, monkeypatch):
    now = set_time(monkeypatch, "2026-10-23T00:00:00.123456+00:00")
    record = client.post("/api/attendance/clock-in", json={
        "user_id": "someone-else", "clock_in_at": "2000-01-01T00:00:00Z",
    }).json()
    assert record["user_id"] == "demo-user"
    assert datetime.fromisoformat(record["clock_in_at"]) == now
    assert datetime.fromisoformat(record["clock_in_at"]).utcoffset() == timedelta(0)


def test_clock_regression_does_not_close_shift(client, monkeypatch):
    set_time(monkeypatch, "2026-10-23T01:00:00+00:00")
    client.post("/api/attendance/clock-in")
    set_time(monkeypatch, "2026-10-23T00:00:00+00:00")
    assert client.post("/api/attendance/clock-out").status_code == 409
    assert client.get("/api/attendance/status").json()["status"] == "working"


@pytest.mark.parametrize("method,path", [
    ("get", "/api/attendance/status"),
    ("get", "/api/attendance/history"),
    ("post", "/api/attendance/clock-in"),
    ("post", "/api/attendance/clock-out"),
])
@pytest.mark.parametrize("db_state", ["missing", "empty", "corrupt"])
def test_database_failures_are_503(tmp_path, monkeypatch, method, path, db_state):
    db = tmp_path / "unavailable.sqlite3"
    monkeypatch.setenv("BAKURAKU_DB_PATH", str(db))
    if db_state == "empty":
        sqlite3.connect(db).close()  # WBS 0.3 DB before schema initialization
    elif db_state == "corrupt":
        db.write_text("not SQLite", encoding="utf-8")
    with TestClient(app) as client:
        response = getattr(client, method)(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
