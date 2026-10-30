"""WBS 1.6: cutoff, durable cooldown, identity, and no auto clock-out."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.attendance_overdue import evaluate_overdue
from app.dependencies import get_clock, get_current_user_id
from app.models import AttendanceRecord as Record
from app.postgres import session_scope

START = datetime(2026, 10, 29, tzinfo=timezone.utc)
OVERDUE_URL = "/api/attendance/overdue"
CONFIRM_URL = "/api/attendance/overdue/confirm"


def test_pure_overdue_boundary_and_cooldown():
    assert evaluate_overdue(None, START).model_dump() == {
        "record_id": None, "overdue_at": None,
        "requires_confirmation": False, "suppressed_until": None, "last_choice": None,
    }
    row = SimpleNamespace(
        id=7, clock_in_at=START, overdue_confirmed_at=None, overdue_confirmed_choice=None,
    )
    assert not evaluate_overdue(row, START + timedelta(hours=16) - timedelta(microseconds=1)).requires_confirmation
    assert evaluate_overdue(row, START + timedelta(hours=16)).requires_confirmation
    row.overdue_confirmed_at = START + timedelta(hours=16)
    row.overdue_confirmed_choice = "still_working"
    assert not evaluate_overdue(row, START + timedelta(hours=17) - timedelta(microseconds=1)).requires_confirmation
    assert evaluate_overdue(row, START + timedelta(hours=17)).requires_confirmation


@pytest.mark.postgres
def test_overdue_lifecycle_is_persistent_and_never_auto_closes(client, api_db, client_factory):
    now = {"value": START}
    client.app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    assert client.get(OVERDUE_URL).json() == {
        "record_id": None, "overdue_at": None, "requires_confirmation": False,
        "suppressed_until": None, "last_choice": None,
    }
    record = client.post("/api/attendance/clock-in").json()
    now["value"] = START + timedelta(hours=16) - timedelta(microseconds=1)
    assert not client.get(OVERDUE_URL).json()["requires_confirmation"]
    assert client.post(CONFIRM_URL, json={"choice": "still_working"}).status_code == 409
    now["value"] = START + timedelta(hours=16)
    assert client.get(OVERDUE_URL).json()["requires_confirmation"]
    confirmed = client.post(CONFIRM_URL, json={"choice": "still_working"})
    assert confirmed.status_code == 200
    assert confirmed.json()["requires_correction"] is False
    assert confirmed.json()["record_id"] == record["id"]
    assert not client.get(OVERDUE_URL).json()["requires_confirmation"]

    # The status stays suppressed across sessions and client instances.
    with client_factory() as another:
        another.app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
        assert not another.get(OVERDUE_URL).json()["requires_confirmation"]
    now["value"] += timedelta(hours=1) - timedelta(microseconds=1)
    assert not client.get(OVERDUE_URL).json()["requires_confirmation"]
    now["value"] += timedelta(microseconds=1)
    assert client.get(OVERDUE_URL).json()["requires_confirmation"]
    with session_scope(api_db) as session:
        row = session.get(Record, record["id"])
        assert row.clock_out_at is None
        assert row.overdue_confirmed_choice == "still_working"


@pytest.mark.postgres
def test_confirmation_idempotency_and_choice_conflict(client, api_db):
    now = {"value": START}
    client.app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    client.post("/api/attendance/clock-in")
    now["value"] = START + timedelta(hours=16)
    first = client.post(CONFIRM_URL, json={"choice": "forgot_clock_out"})
    assert first.status_code == 200
    assert first.json()["requires_correction"] is True
    original = first.json()["suppressed_until"]
    now["value"] += timedelta(minutes=10)
    retry = client.post(CONFIRM_URL, json={"choice": "forgot_clock_out"})
    assert retry.status_code == 200
    assert retry.json()["suppressed_until"] == original
    conflicting = client.post(CONFIRM_URL, json={"choice": "still_working"})
    assert conflicting.status_code == 409
    assert conflicting.json() == {"detail": "Confirmation already handled"}
    assert client.get(OVERDUE_URL).json()["last_choice"] == "forgot_clock_out"
    with session_scope(api_db) as session:
        assert session.scalar(select(Record.clock_out_at)) is None


@pytest.mark.postgres
def test_invalid_choice_missing_and_closed_shift(client):
    assert client.post(CONFIRM_URL, json={"choice": "still_working"}).status_code == 409
    assert client.post(CONFIRM_URL, json={"choice": "wrong"}).status_code == 422
    client.post("/api/attendance/clock-in")
    client.post("/api/attendance/clock-out")
    assert client.post(CONFIRM_URL, json={"choice": "still_working"}).status_code == 409
    assert client.get(OVERDUE_URL).json()["record_id"] is None


@pytest.mark.postgres
def test_overdue_is_isolated_by_identity(client, demo_id, other_id):
    now = {"value": START}
    client.app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    client.post("/api/attendance/clock-in")
    now["value"] = START + timedelta(hours=17)
    client.app.dependency_overrides[get_current_user_id] = lambda: other_id
    assert client.get(OVERDUE_URL).json()["record_id"] is None
    assert client.post(CONFIRM_URL, json={"choice": "still_working"}).status_code == 409
    client.app.dependency_overrides[get_current_user_id] = lambda: demo_id
    assert client.get(OVERDUE_URL).json()["requires_confirmation"]


@pytest.mark.postgres
def test_concurrent_same_choice_does_not_extend_cooldown(client, api_db):
    now = {"value": START}
    client.app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    client.post("/api/attendance/clock-in")
    now["value"] = START + timedelta(hours=16)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: client.post(CONFIRM_URL, json={"choice": "still_working"}), range(2),
        ))
    assert [r.status_code for r in results] == [200, 200]
    assert len({r.json()["suppressed_until"] for r in results}) == 1
    with session_scope(api_db) as session:
        row = session.scalar(select(Record))
        assert row.overdue_confirmed_at == now["value"]


@pytest.mark.postgres
def test_clockout_removes_record_from_active_overdue_state(client):
    now = {"value": START}
    client.app.dependency_overrides[get_clock] = lambda: lambda: now["value"]
    client.post("/api/attendance/clock-in")
    now["value"] = START + timedelta(hours=16)
    assert client.post(CONFIRM_URL, json={"choice": "still_working"}).status_code == 200
    assert client.post("/api/attendance/clock-out").status_code == 200
    assert client.get(OVERDUE_URL).json()["record_id"] is None
