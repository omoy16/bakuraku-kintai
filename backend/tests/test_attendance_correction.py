"""Real PostgreSQL tests for editing, history, owner isolation and atomicity."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select, text

from app import attendance_correction
from app.dependencies import get_clock, get_current_user_id
from app.models import AttendanceAuditLog as Audit, AttendanceRecord as Record
from app.postgres import session_scope
from app.schemas import AttendanceCorrectionRequest

pytestmark = pytest.mark.postgres
START = datetime(2026, 10, 29, tzinfo=timezone.utc)
NOW = START + timedelta(days=4)
PREFIX = "/api/attendance"


def at(client, when):
    client.app.dependency_overrides[get_clock] = lambda: lambda: when


def shift(client, start=START, end=None):
    at(client, start)
    response = client.post(PREFIX + "/clock-in")
    assert response.status_code == 201
    record_id = response.json()["id"]
    if end is not None:
        at(client, end)
        assert client.post(PREFIX + "/clock-out").status_code == 200
    at(client, NOW)
    return client.get(f"{PREFIX}/records/{record_id}").json()


def correction(record, **changes):
    return {
        "clock_in_at": record["clock_in_at"],
        "clock_out_at": (START + timedelta(hours=8)).isoformat(),
        "expected_operation_id": record["latest_operation_id"],
        "change_reason": "退勤打刻を忘れたため",
    } | changes


def patch(client, record, **changes):
    return client.patch(f"{PREFIX}/records/{record['id']}", json=correction(record, **changes))


def audit_count(engine):
    with session_scope(engine) as session:
        return session.scalar(select(func.count()).select_from(Audit))


def test_forgotten_clock_out_is_corrected_with_durable_before_after_and_reason(
    client, api_db, demo_id, client_factory,
):
    record = shift(client)
    assert record["is_modified"] is False
    assert client.post(PREFIX + "/overdue/confirm", json={"choice": "forgot_clock_out"}).status_code == 200
    with session_scope(api_db) as session:
        session.get(Record, record["id"]).reminder_sent_at = START + timedelta(hours=16)
    response = patch(client, record, change_reason="  退勤打刻を忘れたため  ")
    assert response.status_code == 200
    edited = response.json()
    assert edited["id"] == record["id"]
    assert edited["user_id"] == demo_id
    assert edited["is_modified"] is True
    assert edited["latest_operation_id"] > record["latest_operation_id"]
    assert client.get(PREFIX + "/status").json()["status"] == "not_working"
    assert client.get(PREFIX + "/overdue").json()["requires_confirmation"] is False
    with client_factory() as fresh:
        assert fresh.get(f"{PREFIX}/records/{record['id']}").json() == edited
        logs = fresh.get(f"{PREFIX}/records/{record['id']}/audit-logs").json()
    assert [log["operation"] for log in logs] == ["update", "clock_in"]
    assert logs[0]["actor_user_id"] == demo_id
    assert logs[0]["attendance_record_id"] == record["id"]
    assert logs[0]["change_reason"] == "退勤打刻を忘れたため"
    assert logs[0]["before_values"] == logs[1]["after_values"]
    assert datetime.fromisoformat(logs[0]["after_values"]["clock_out_at"]) == START + timedelta(hours=8)
    assert datetime.fromisoformat(logs[0]["operated_at"]).utcoffset() == timedelta(0)
    assert logs[1]["before_values"] is None
    with session_scope(api_db) as session:
        row = session.get(Record, record["id"])
        assert row.reminder_sent_at == START + timedelta(hours=16)
        assert row.overdue_confirmed_at is None
        assert row.overdue_confirmed_choice is None
        assert row.updated_at > row.created_at
    assert client.post(PREFIX + "/cancel").json() == {"detail": "No cancellable punch"}


def test_reopening_completed_shift_is_explicit_and_changes_working_status(client):
    record = shift(client, end=START + timedelta(hours=8))
    response = patch(client, record, clock_out_at=None)
    assert response.status_code == 200
    assert response.json()["clock_out_at"] is None
    assert client.get(PREFIX + "/status").json()["active_record"]["id"] == record["id"]


def test_jst_date_crossing_edit_keeps_id_and_reorders_history(client):
    first = shift(client, end=START + timedelta(hours=8))
    second = shift(client, start=START + timedelta(days=1), end=START + timedelta(days=1, hours=8))
    response = patch(client, second, clock_in_at="2026-10-28T22:00:00+09:00",
                     clock_out_at="2026-10-29T07:00:00+09:00")
    assert response.status_code == 200
    assert response.json()["id"] == second["id"]
    assert datetime.fromisoformat(response.json()["clock_in_at"]) == START - timedelta(hours=11)
    records = client.get(PREFIX + "/records").json()
    assert [r["id"] for r in records] == [first["id"], second["id"]]
    assert [r["is_modified"] for r in records] == [False, True]
    # The existing frontend continues to receive its original four fields.
    legacy = client.get(PREFIX + "/history").json()
    assert [r["id"] for r in legacy] == [first["id"], second["id"]]
    assert set(legacy[0]) == {"id", "user_id", "clock_in_at", "clock_out_at"}


def test_cancelled_record_is_readable_only_by_owner_and_cannot_be_corrected(client, api_db):
    record = shift(client)
    assert client.post(PREFIX + "/cancel").status_code == 200
    assert client.get(PREFIX + "/records").json() == []
    detail = client.get(f"{PREFIX}/records/{record['id']}").json()
    assert detail["cancelled_at"] is not None
    logs = client.get(f"{PREFIX}/records/{record['id']}/audit-logs").json()
    assert logs[0]["operation"] == "cancel_clock_in"
    count = audit_count(api_db)
    assert patch(client, detail).status_code == 409
    assert audit_count(api_db) == count


@pytest.mark.parametrize("missing", [False, True])
def test_other_users_and_unknown_ids_share_404(client, api_db, demo_id, other_id, missing):
    record = shift(client)
    if missing:
        record["id"] += 10000
    else:
        client.app.dependency_overrides[get_current_user_id] = lambda: other_id
    if not missing:
        assert client.get(PREFIX + "/records").json() == []
    for suffix in ["", "/audit-logs"]:
        response = client.get(f"{PREFIX}/records/{record['id']}{suffix}", params={"user_id": demo_id})
        assert response.status_code == 404
        assert response.json() == {"detail": "Attendance record not found"}
    assert patch(client, record).status_code == 404
    assert audit_count(api_db) == 1


def test_invalid_request_is_422_and_client_cannot_set_owner_or_audit(client, api_db):
    record = shift(client)
    assert patch(client, record, clock_out_at="2026-10-28T00:00:00Z").status_code == 422
    assert patch(client, record, user_id=999).status_code == 422
    assert patch(client, record, operated_at="2000-01-01T00:00:00Z").status_code == 422
    assert audit_count(api_db) == 1


@pytest.mark.parametrize("clock_in,clock_out,detail", [
    ((START + timedelta(days=5)).isoformat(), None, "Attendance time cannot be in the future"),
    (START.isoformat(), (START + timedelta(days=5)).isoformat(), "Attendance time cannot be in the future"),
    (START.isoformat(), None, "Attendance times are unchanged"),
])
def test_future_times_and_noop_edits_do_not_append_logs(client, api_db, clock_in, clock_out, detail):
    record = shift(client)
    response = patch(client, record, clock_in_at=clock_in, clock_out_at=clock_out)
    assert response.status_code == 409
    assert response.json() == {"detail": detail}
    assert client.get(f"{PREFIX}/records/{record['id']}").json() == record
    assert audit_count(api_db) == 1


def test_stale_revision_is_rejected_even_when_values_returned_to_original(client, api_db):
    record = shift(client, end=START + timedelta(hours=8))
    first = patch(client, record, clock_out_at=(START + timedelta(hours=7)).isoformat()).json()
    second = patch(client, first, clock_out_at=record["clock_out_at"]).json()
    response = patch(client, record, clock_out_at=(START + timedelta(hours=6)).isoformat())
    assert response.status_code == 409
    assert response.json() == {"detail": "Attendance has changed; reload before correcting"}
    assert client.get(f"{PREFIX}/records/{record['id']}").json() == second
    assert audit_count(api_db) == 4


@pytest.mark.parametrize("kind", ["overlap", "second_active", "adjacent", "empty"])
def test_database_constraints_reject_conflicts_and_allow_boundaries(client, api_db, kind):
    first = shift(client, end=START + timedelta(hours=8))
    shift(client, start=START + timedelta(hours=9), end=None if kind == "second_active" else START + timedelta(hours=16))
    changes = {"clock_out_at": (START + timedelta(hours=10)).isoformat()}
    if kind == "second_active":
        changes = {"clock_out_at": None}
    elif kind == "adjacent":
        changes = {"clock_out_at": (START + timedelta(hours=9)).isoformat()}
    elif kind == "empty":
        changes = {"clock_in_at": (START + timedelta(hours=10)).isoformat(),
                   "clock_out_at": (START + timedelta(hours=10)).isoformat()}
    before_count = audit_count(api_db)
    response = patch(client, first, **changes)
    assert response.status_code == (409 if kind in {"overlap", "second_active"} else 200)
    assert audit_count(api_db) == before_count + (response.status_code == 200)
    if response.status_code == 409:
        assert client.get(f"{PREFIX}/records/{first['id']}").json() == first


def test_record_without_previous_audit_uses_explicit_null_revision(client, api_db, demo_id):
    with session_scope(api_db) as session:
        record = Record(user_id=demo_id, clock_in_at=START)
        session.add(record)
        session.flush()
        record_id = record.id
    at(client, NOW)
    detail = client.get(f"{PREFIX}/records/{record_id}").json()
    assert detail["latest_operation_id"] is None
    assert client.get(f"{PREFIX}/records/{record_id}/audit-logs").json() == []
    response = patch(client, detail)
    assert response.status_code == 200
    assert response.json()["latest_operation_id"] is not None


def test_simultaneous_edits_allow_one_success(client, api_db):
    record = shift(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda hours: patch(client, record,
            clock_out_at=(START + timedelta(hours=hours)).isoformat()), [7, 8]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert audit_count(api_db) == 2


@pytest.mark.parametrize("action", ["clock-out", "cancel"])
def test_edit_serializes_with_punch_and_cancel_without_overwrite(client, api_db, action):
    record = shift(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        edit = pool.submit(patch, client, record)
        other = pool.submit(client.post, f"{PREFIX}/{action}")
        responses = [edit.result(), other.result()]
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert audit_count(api_db) == 2


@pytest.mark.parametrize("when", ["flush", "commit"])
def test_audit_failure_rolls_back_correction_and_metadata(client, api_db, monkeypatch, when):
    record = shift(client)
    if when == "flush":
        original = attendance_correction.write_audit

        def reject(session, row, operation, before, **kwargs):
            original(session, row, "invalid_operation", before, **kwargs)

        monkeypatch.setattr(attendance_correction, "write_audit", reject)
    else:
        with api_db.begin() as connection:
            connection.execute(text("""
                CREATE FUNCTION reject_correction_commit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'private correction failure'; END; $$
            """))
            connection.execute(text("""
                CREATE CONSTRAINT TRIGGER reject_correction_commit AFTER INSERT ON attendance_audit_logs
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_correction_commit()
            """))
    try:
        response = patch(client, record)
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
    finally:
        if when == "commit":
            with api_db.begin() as connection:
                connection.execute(text("DROP TRIGGER reject_correction_commit ON attendance_audit_logs"))
                connection.execute(text("DROP FUNCTION reject_correction_commit()"))
    assert client.get(f"{PREFIX}/records/{record['id']}").json() == record
    assert audit_count(api_db) == 1


def test_detail_values_and_revision_come_from_same_read_snapshot(client, api_db, demo_id):
    record = shift(client)
    changed = False

    def update_after_select(connection, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if changed or "FROM attendance_records" not in statement or not statement.startswith("SELECT"):
            return
        changed = True
        attendance_correction.correct_record(api_db, demo_id, record["id"],
            AttendanceCorrectionRequest.model_validate(correction(record)), lambda: NOW)

    event.listen(api_db, "after_cursor_execute", update_after_select)
    try:
        response = client.get(f"{PREFIX}/records/{record['id']}")
    finally:
        event.remove(api_db, "after_cursor_execute", update_after_select)
    assert changed
    assert response.json() == record  # old values must carry the old revision
    current = client.get(f"{PREFIX}/records/{record['id']}").json()
    assert current["latest_operation_id"] != record["latest_operation_id"]
    assert current["clock_out_at"] is not None
