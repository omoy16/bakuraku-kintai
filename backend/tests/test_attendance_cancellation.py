"""WBS 1.5: cancellation boundaries, audit consistency, ownership, and locking."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app import attendance_cancellation
from app.dependencies import get_current_user_id
from app.models import AttendanceAuditLog as Audit, AttendanceRecord as Record
from app.postgres import session_scope

pytestmark = pytest.mark.postgres
START = datetime(2026, 10, 29, tzinfo=timezone.utc)


def counts(engine):
    with session_scope(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(Record)),
            session.scalar(select(func.count()).select_from(Audit)),
        )


def test_nothing_to_cancel_is_409(client, api_db):
    response = client.post("/api/attendance/cancel")
    assert response.status_code == 409
    assert response.json() == {"detail": "No cancellable punch"}
    assert counts(api_db) == (0, 0)


def test_cancel_clock_in_keeps_record_and_appends_audit(client, api_db, demo_id):
    original = client.post("/api/attendance/clock-in").json()
    response = client.post("/api/attendance/cancel")
    assert response.status_code == 200
    assert response.json() == {
        "record_id": original["id"],
        "cancelled_operation": "clock_in",
        "status": "not_working",
    }
    assert client.get("/api/attendance/status").json()["status"] == "not_working"
    assert client.get("/api/attendance/history").json() == []
    with session_scope(api_db) as session:
        record = session.get(Record, original["id"])
        logs = session.scalars(select(Audit).order_by(Audit.id)).all()
        assert record.user_id == demo_id
        assert record.cancelled_at is not None
        assert record.clock_out_at is None
        assert [log.operation for log in logs] == ["clock_in", "cancel_clock_in"]
        assert logs[1].actor_user_id == demo_id
        assert logs[1].before_values == logs[0].after_values
        assert logs[1].after_values["cancelled_at"] is not None
    assert counts(api_db) == (1, 2)


def test_cancel_clock_out_reopens_same_shift(client, api_db):
    original = client.post("/api/attendance/clock-in").json()
    finished = client.post("/api/attendance/clock-out").json()
    assert finished["id"] == original["id"]

    response = client.post("/api/attendance/cancel")
    assert response.status_code == 200
    assert response.json() == {
        "record_id": original["id"],
        "cancelled_operation": "clock_out",
        "status": "working",
    }
    status = client.get("/api/attendance/status").json()
    assert status["status"] == "working"
    assert status["active_record"] == original
    with session_scope(api_db) as session:
        record = session.get(Record, original["id"])
        logs = session.scalars(select(Audit).order_by(Audit.id)).all()
        assert record.clock_out_at is None
        assert record.cancelled_at is None
        assert [log.operation for log in logs] == [
            "clock_in", "clock_out", "cancel_clock_out",
        ]
        assert logs[2].before_values == logs[1].after_values
        assert logs[2].after_values == logs[0].after_values


@pytest.mark.parametrize("age,expected_status", [
    (0, 200),
    (60, 200),
    (60.000001, 409),
    (-1, 409),
])
@pytest.mark.parametrize("last_punch", ["clock_in", "clock_out"])
def test_60_second_boundary_uses_db_audit_time_not_punch_time(
    client, api_db, monkeypatch, age, expected_status, last_punch,
):
    # The punch timestamp can differ from the stored operation timestamp.
    client.post("/api/attendance/clock-in")
    if last_punch == "clock_out":
        assert client.post("/api/attendance/clock-out").status_code == 200
    before = client.get("/api/attendance/status").json()
    audit_count = 1 if last_punch == "clock_in" else 2
    with session_scope(api_db) as session:
        log = session.scalar(select(Audit).where(Audit.operation == last_punch))
        log.operated_at = START
    monkeypatch.setattr(
        attendance_cancellation, "db_now",
        lambda session: START + timedelta(seconds=age),
    )
    response = client.post("/api/attendance/cancel")
    assert response.status_code == expected_status
    if expected_status == 409:
        assert response.json() == {"detail": "Cancellation window expired"}
        assert client.get("/api/attendance/status").json() == before
        assert counts(api_db) == (1, audit_count)
    else:
        assert response.json()["cancelled_operation"] == last_punch
        assert client.get("/api/attendance/status").json()["status"] == (
            "not_working" if last_punch == "clock_in" else "working"
        )
        assert counts(api_db) == (1, audit_count + 1)


def test_second_cancel_is_rejected_without_further_changes(client, api_db):
    client.post("/api/attendance/clock-in")
    assert client.post("/api/attendance/cancel").status_code == 200
    response = client.post("/api/attendance/cancel")
    assert response.status_code == 409
    assert response.json() == {"detail": "No cancellable punch"}
    assert counts(api_db) == (1, 2)


def test_cancel_applies_only_to_current_user(client, api_db, demo_id, other_id):
    own = client.post("/api/attendance/clock-in").json()
    client.app.dependency_overrides[get_current_user_id] = lambda: other_id
    assert client.post("/api/attendance/cancel").status_code == 409
    another = client.post("/api/attendance/clock-in").json()
    response = client.post("/api/attendance/cancel", json={"user_id": demo_id})
    assert response.status_code == 200
    assert response.json()["record_id"] == another["id"]
    client.app.dependency_overrides[get_current_user_id] = lambda: demo_id
    assert client.get("/api/attendance/status").json()["active_record"] == own


def test_simultaneous_cancels_allow_only_one_success(client, api_db):
    client.post("/api/attendance/clock-in")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda _: client.post("/api/attendance/cancel"), range(2),
        ))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert counts(api_db) == (1, 2)


@pytest.mark.parametrize("last_punch", ["clock_in", "clock_out"])
def test_cancel_audit_failure_rolls_back_shift(client, api_db, monkeypatch, last_punch):
    client.post("/api/attendance/clock-in")
    if last_punch == "clock_out":
        client.post("/api/attendance/clock-out")
    before = client.get("/api/attendance/status").json()
    audit_before = counts(api_db)
    original_write = attendance_cancellation.write_audit

    def invalid_audit(session, record, operation, previous):
        original_write(session, record, "invalid_operation", previous)

    monkeypatch.setattr(attendance_cancellation, "write_audit", invalid_audit)
    response = client.post("/api/attendance/cancel")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert client.get("/api/attendance/status").json() == before
    assert counts(api_db) == audit_before


@pytest.mark.parametrize("last_punch", ["clock_in", "clock_out"])
def test_cancel_commit_failure_rolls_back_and_can_be_retried(client, api_db, last_punch):
    client.post("/api/attendance/clock-in")
    if last_punch == "clock_out":
        assert client.post("/api/attendance/clock-out").status_code == 200
    before = client.get("/api/attendance/status").json()
    audit_before = counts(api_db)
    with api_db.begin() as connection:
        connection.execute(text("""
            CREATE FUNCTION reject_cancel_commit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private cancellation failure'; END; $$
        """))
        connection.execute(text("""
            CREATE CONSTRAINT TRIGGER reject_cancel_commit AFTER INSERT ON attendance_audit_logs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_cancel_commit()
        """))
    try:
        response = client.post("/api/attendance/cancel")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
    finally:
        with api_db.begin() as connection:
            connection.execute(text("DROP TRIGGER reject_cancel_commit ON attendance_audit_logs"))
            connection.execute(text("DROP FUNCTION reject_cancel_commit()"))
    assert client.get("/api/attendance/status").json() == before
    assert counts(api_db) == audit_before
    assert client.post("/api/attendance/cancel").status_code == 200
    assert counts(api_db) == (audit_before[0], audit_before[1] + 1)


def test_latest_punch_only_and_earlier_shift_is_not_reopened(client, api_db):
    old = client.post("/api/attendance/clock-in").json()
    client.post("/api/attendance/clock-out")
    newest = client.post("/api/attendance/clock-in").json()
    response = client.post("/api/attendance/cancel")
    assert response.status_code == 200
    assert response.json()["record_id"] == newest["id"]
    assert client.post("/api/attendance/cancel").status_code == 409
    with session_scope(api_db) as session:
        assert session.get(Record, old["id"]).clock_out_at is not None
        assert session.get(Record, newest["id"]).cancelled_at is not None
