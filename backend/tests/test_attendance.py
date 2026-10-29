"""PostgreSQL HTTP transitions, audit atomicity, overnight shifts, and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app import attendance_service
from app.dependencies import get_clock
from app.models import AttendanceAuditLog as Audit, AttendanceRecord as Record, User
from app.postgres import session_scope
from app.seed_demo_user import seed_demo_user

pytestmark = pytest.mark.postgres
START = datetime(2026, 10, 29, tzinfo=timezone.utc)


def set_time(client, value):
    now = datetime.fromisoformat(value)
    client.app.dependency_overrides[get_clock] = lambda: lambda: now
    return now


def counts(engine):
    with session_scope(engine) as session:
        return (session.scalar(select(func.count()).select_from(Record)),
                session.scalar(select(func.count()).select_from(Audit)))


def test_punch_cycle_persists_and_can_start_another_shift(client, demo_id, api_db, client_factory):
    assert client.get("/api/attendance/status").json() == {
        "user_id": demo_id, "status": "not_working", "active_record": None,
    }
    start = set_time(client, "2026-10-29T00:00:00+00:00")
    response = client.post("/api/attendance/clock-in")
    assert response.status_code == 201
    record = response.json()
    assert record["user_id"] == demo_id
    assert datetime.fromisoformat(record["clock_in_at"]) == start
    assert record["clock_out_at"] is None
    with client_factory() as fresh_client:
        assert fresh_client.get("/api/attendance/status").json()["active_record"] == record
    end = set_time(client, "2026-10-29T09:00:00+00:00")
    finished = client.post("/api/attendance/clock-out")
    assert finished.status_code == 200
    assert finished.json()["id"] == record["id"]
    assert datetime.fromisoformat(finished.json()["clock_out_at"]) == end
    assert client.get("/api/attendance/status").json()["status"] == "not_working"
    assert client.post("/api/attendance/clock-in").status_code == 201
    assert counts(api_db) == (2, 3)


def test_history_is_empty_before_first_punch(client):
    response = client.get("/api/attendance/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_filters_owner_and_cancelled_rows_and_orders_newest_first(
    client, api_db, demo_id, other_id,
):
    set_time(client, "2026-10-27T00:00:00+00:00")
    first = client.post("/api/attendance/clock-in").json()
    set_time(client, "2026-10-27T08:00:00+00:00")
    client.post("/api/attendance/clock-out")
    with session_scope(api_db) as session:
        session.add_all([
            Record(user_id=other_id, clock_in_at=START),
            Record(user_id=demo_id, clock_in_at=START, cancelled_at=START),
        ])
    set_time(client, "2026-10-29T01:00:00+00:00")
    second = client.post("/api/attendance/clock-in").json()
    response = client.get("/api/attendance/history")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [second["id"], first["id"]]
    assert {row["user_id"] for row in response.json()} == {demo_id}


def test_invalid_transitions_do_not_change_records_or_audit(client, api_db):
    assert client.post("/api/attendance/clock-out").json() == {"detail": "Not working"}
    record = client.post("/api/attendance/clock-in").json()
    response = client.post("/api/attendance/clock-in")
    assert response.status_code == 409
    assert response.json() == {"detail": "Already working"}
    assert client.get("/api/attendance/status").json()["active_record"] == record
    assert client.post("/api/attendance/clock-out").status_code == 200
    response = client.post("/api/attendance/clock-out")
    assert response.status_code == 409
    assert response.json() == {"detail": "Not working"}
    assert counts(api_db) == (1, 2)


@pytest.mark.parametrize("start,end", [
    ("2026-10-27T14:30:00+00:00", "2026-10-27T16:00:00+00:00"),
    ("2026-10-27T23:30:00+00:00", "2026-10-28T01:00:00+00:00"),
    ("2026-10-27T00:00:00+00:00", "2026-10-29T00:00:00+00:00"),
])
def test_overnight_and_long_running_shifts(client, start, end):
    set_time(client, start)
    record = client.post("/api/attendance/clock-in").json()
    set_time(client, end)
    assert client.get("/api/attendance/status").json()["active_record"] == record
    assert client.post("/api/attendance/clock-in").status_code == 409
    response = client.post("/api/attendance/clock-out")
    assert response.status_code == 200
    assert response.json()["id"] == record["id"]
    assert datetime.fromisoformat(response.json()["clock_out_at"]) == datetime.fromisoformat(end)


@pytest.mark.parametrize("action,success,audit_count", [
    ("clock-in", 201, 1), ("clock-out", 200, 2),
])
def test_concurrent_punches_allow_one_success(client, api_db, action, success, audit_count):
    if action == "clock-out":
        assert client.post("/api/attendance/clock-in").status_code == 201
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda _: client.post(f"/api/attendance/{action}"), range(2),
        ))
    assert sorted(r.status_code for r in responses) == sorted([success, 409])
    assert counts(api_db) == (1, audit_count)


def test_user_and_timestamps_are_server_controlled(client, demo_id):
    now = set_time(client, "2026-10-29T00:00:00.123456+00:00")
    fake = {"user_id": 999, "clock": "fake", "clock_in_at": "2000-01-01T00:00:00Z"}
    response = client.post("/api/attendance/clock-in", json=fake, params=fake)
    assert response.status_code == 201
    record = response.json()
    assert record["user_id"] == demo_id
    assert datetime.fromisoformat(record["clock_in_at"]) == now
    assert datetime.fromisoformat(record["clock_in_at"]).utcoffset() == timedelta(0)


def test_clock_regression_does_not_close_shift_or_append_audit(client, api_db):
    set_time(client, "2026-10-29T01:00:00+00:00")
    record = client.post("/api/attendance/clock-in").json()
    set_time(client, "2026-10-29T00:00:00+00:00")
    response = client.post("/api/attendance/clock-out")
    assert response.status_code == 409
    assert response.json() == {"detail": "Clock is earlier than clock-in time"}
    assert client.get("/api/attendance/status").json()["active_record"] == record
    assert counts(api_db) == (1, 1)


def test_audit_snapshots_use_utc_and_generated_actor_id(client, api_db, demo_id):
    set_time(client, "2026-10-28T23:30:00+00:00")
    record = client.post("/api/attendance/clock-in").json()
    set_time(client, "2026-10-29T08:30:00+00:00")
    client.post("/api/attendance/clock-out")
    with session_scope(api_db) as session:
        logs = session.scalars(select(Audit).order_by(Audit.id)).all()
        assert [row.operation for row in logs] == ["clock_in", "clock_out"]
        assert all(row.actor_user_id == demo_id for row in logs)
        assert all(row.attendance_record_id == record["id"] for row in logs)
        assert logs[0].before_values is None
        assert logs[1].before_values == logs[0].after_values
        assert logs[0].after_values == {
            "clock_in_at": "2026-10-28T23:30:00+00:00",
            "clock_out_at": None, "cancelled_at": None,
        }
        assert logs[1].after_values["clock_out_at"] == "2026-10-29T08:30:00+00:00"


def test_overlap_constraint_is_409_and_leaves_no_new_punch_or_audit(client, api_db, demo_id):
    with session_scope(api_db) as session:
        session.add(Record(user_id=demo_id, clock_in_at=START,
                           clock_out_at=START + timedelta(hours=8)))
    set_time(client, "2026-10-28T23:00:00+00:00")
    response = client.post("/api/attendance/clock-in")
    assert response.status_code == 409
    assert response.json() == {"detail": "Attendance period overlaps existing record"}
    assert counts(api_db) == (1, 0)


@pytest.mark.parametrize("action", ["clock-in", "clock-out"])
def test_audit_insert_failure_rolls_back_attendance(client, api_db, monkeypatch, action):
    if action == "clock-out":
        assert client.post("/api/attendance/clock-in").status_code == 201
    before = client.get("/api/attendance/status").json()
    original = attendance_service.write_audit

    def invalid_audit(session, row, operation, previous):
        original(session, row, "invalid_operation", previous)

    monkeypatch.setattr(attendance_service, "write_audit", invalid_audit)
    response = client.post(f"/api/attendance/{action}")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert client.get("/api/attendance/status").json() == before
    assert counts(api_db) == ((0, 0) if action == "clock-in" else (1, 1))


@pytest.mark.parametrize("action", ["clock-in", "clock-out"])
def test_failure_deferred_until_commit_is_503_and_rolls_back_both_writes(client, api_db, action):
    if action == "clock-out":
        client.post("/api/attendance/clock-in")
    before = client.get("/api/attendance/status").json()
    with api_db.begin() as connection:
        connection.execute(text("""
            CREATE FUNCTION reject_audit_commit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private commit failure'; END; $$
        """))
        connection.execute(text("""
            CREATE CONSTRAINT TRIGGER reject_audit_commit
            AFTER INSERT ON attendance_audit_logs DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION reject_audit_commit()
        """))
    try:
        response = client.post(f"/api/attendance/{action}")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
    finally:
        with api_db.begin() as connection:
            connection.execute(text("DROP TRIGGER reject_audit_commit ON attendance_audit_logs"))
            connection.execute(text("DROP FUNCTION reject_audit_commit()"))
    assert client.get("/api/attendance/status").json() == before
    assert counts(api_db) == ((0, 0) if action == "clock-in" else (1, 1))


def test_clock_is_read_after_user_lock_and_other_users_are_not_locked(
    client, api_db, demo_id, other_id,
):
    calls = []

    def clock():
        with pytest.raises(DBAPIError) as error:
            with session_scope(api_db) as other:
                other.scalar(select(User.id).where(User.id == demo_id).with_for_update(nowait=True))
        assert error.value.orig.sqlstate == "55P03"
        with session_scope(api_db) as other:
            assert other.scalar(
                select(User.id).where(User.id == other_id).with_for_update(nowait=True)
            ) == other_id
        calls.append(START)
        return START

    client.app.dependency_overrides[get_clock] = lambda: clock
    assert client.post("/api/attendance/clock-out").status_code == 409
    assert not calls
    assert client.post("/api/attendance/clock-in").status_code == 201
    assert client.post("/api/attendance/clock-in").status_code == 409
    assert calls == [START]


def test_seeded_demo_identity_is_not_assumed_to_be_one(api_db, other_id, client_factory):
    user_id = seed_demo_user(api_db)
    assert user_id != other_id
    with client_factory() as client:
        assert client.get("/api/attendance/status").json()["user_id"] == user_id
        assert client.post("/api/attendance/clock-in").json()["user_id"] == user_id


def test_missing_seed_is_not_automatically_recreated(api_db, client_factory):
    with client_factory() as client:
        assert client.get("/api/health/db").status_code == 200
        response = client.post("/api/attendance/clock-in")
        assert response.status_code == 503
    with session_scope(api_db) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
    assert counts(api_db) == (0, 0)


def test_dev_init_and_explicit_seed_work_from_another_directory(api_db, tmp_path):
    root = Path(__file__).resolve().parents[2]
    directory = tmp_path / "folder with spaces"
    directory.mkdir()
    env = {**os.environ, "BAKURAKU_DATABASE_URL":
           api_db.url.render_as_string(hide_password=False)}
    for action in ("init-db", "init-db", "seed-demo", "seed-demo"):
        result = subprocess.run([sys.executable, str(root / "dev.py"), action],
                                cwd=directory, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    with session_scope(api_db) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
    assert counts(api_db) == (0, 0)
