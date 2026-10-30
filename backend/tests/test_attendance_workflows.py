"""WBS 1.8: HTTP workflows spanning punches, confirmation, correction and undo."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest

from app.dependencies import get_clock

pytestmark = pytest.mark.postgres
PREFIX = "/api/attendance"
START = datetime.fromisoformat("2026-10-29T22:00:00+09:00")


def at(client, value):
    client.app.dependency_overrides[get_clock] = lambda: lambda: value


def detail(client, record_id):
    response = client.get(f"{PREFIX}/records/{record_id}")
    assert response.status_code == 200
    return response.json()


def edit(client, record, end, **changes):
    payload = {
        "clock_in_at": record["clock_in_at"],
        "clock_out_at": end.isoformat() if end is not None else None,
        "expected_operation_id": record["latest_operation_id"],
        "change_reason": "退勤時刻を訂正",
    } | changes
    return client.patch(f"{PREFIX}/records/{record['id']}", json=payload)


def assert_audit_chain(client, record_id, operations):
    response = client.get(f"{PREFIX}/records/{record_id}/audit-logs")
    assert response.status_code == 200
    logs = list(reversed(response.json()))
    assert [log["operation"] for log in logs] == operations
    assert logs[0]["before_values"] is None
    for previous, current in zip(logs, logs[1:]):
        assert current["before_values"] == previous["after_values"]
    assert all(log["attendance_record_id"] == record_id for log in logs)
    return logs


def test_overnight_forgotten_checkout_then_correct_and_cancel_next_shift(
    client, client_factory, demo_id,
):
    at(client, START)
    response = client.post(PREFIX + "/clock-in")
    assert response.status_code == 201
    record_id = response.json()["id"]
    at(client, START + timedelta(hours=16))
    assert client.get(PREFIX + "/overdue").json()["requires_confirmation"] is True
    assert client.post(PREFIX + "/clock-in").status_code == 409
    confirmed = client.post(PREFIX + "/overdue/confirm", json={"choice": "forgot_clock_out"})
    assert confirmed.status_code == 200
    assert confirmed.json()["requires_correction"] is True
    record = detail(client, record_id)
    assert record["clock_out_at"] is None

    response = edit(client, record, START + timedelta(hours=9))
    assert response.status_code == 200
    corrected = response.json()
    assert datetime.fromisoformat(corrected["clock_out_at"]) == START + timedelta(hours=9)
    assert corrected["is_modified"] is True
    assert client.post(PREFIX + "/cancel").status_code == 409
    next_shift = client.post(PREFIX + "/clock-in")
    assert next_shift.status_code == 201
    next_id = next_shift.json()["id"]
    assert next_id != record_id
    assert client.post(PREFIX + "/cancel").status_code == 200
    cancelled = detail(client, next_id)
    assert cancelled["cancelled_at"] is not None
    assert client.get(PREFIX + "/status").json()["status"] == "not_working"
    assert client.get(PREFIX + "/overdue").json()["record_id"] is None

    with client_factory() as fresh:
        assert fresh.get(PREFIX + "/records").json() == [corrected]
        assert [r["id"] for r in fresh.get(PREFIX + "/history").json()] == [record_id]
        assert detail(fresh, next_id) == cancelled
        for target, operations in [
            (record_id, ["clock_in", "update"]),
            (next_id, ["clock_in", "cancel_clock_in"]),
        ]:
            logs = assert_audit_chain(fresh, target, operations)
            assert all(log["actor_user_id"] == demo_id for log in logs)


def test_correct_reopen_checkout_undo_and_correct_again_preserves_history(client):
    at(client, START)
    record_id = client.post(PREFIX + "/clock-in").json()["id"]
    at(client, START + timedelta(hours=9))
    assert client.post(PREFIX + "/clock-out").status_code == 200
    original = detail(client, record_id)
    at(client, START + timedelta(hours=10))
    reopened = edit(client, original, None)
    assert reopened.status_code == 200
    assert reopened.json()["clock_out_at"] is None

    at(client, START + timedelta(hours=11))
    assert client.post(PREFIX + "/clock-out").status_code == 200
    completed = detail(client, record_id)
    assert completed["is_modified"] is True
    assert edit(client, original, START + timedelta(hours=8)).status_code == 409
    assert client.post(PREFIX + "/cancel").status_code == 200
    after_cancel = detail(client, record_id)
    assert after_cancel["clock_out_at"] is None
    assert after_cancel["is_modified"] is True
    assert after_cancel["latest_operation_id"] > completed["latest_operation_id"]
    assert client.post(PREFIX + "/cancel").status_code == 409
    assert edit(client, completed, START + timedelta(hours=8)).status_code == 409
    fixed = edit(client, after_cancel, START + timedelta(hours=10, minutes=30))
    assert fixed.status_code == 200
    assert client.post(PREFIX + "/cancel").status_code == 409
    assert client.get(PREFIX + "/status").json()["status"] == "not_working"
    assert client.get(PREFIX + "/records").json() == [fixed.json()]
    logs = assert_audit_chain(client, record_id, [
        "clock_in", "clock_out", "update", "clock_out", "cancel_clock_out", "update",
    ])
    assert logs[-1]["id"] == fixed.json()["latest_operation_id"]
    assert logs[-1]["change_reason"] == "退勤時刻を訂正"


@pytest.mark.parametrize("hours,requires_confirmation", [(-1, True), (2, False)])
def test_corrected_active_shift_recalculates_overdue_and_clears_old_confirmation(
    client, hours, requires_confirmation,
):
    at(client, START)
    record_id = client.post(PREFIX + "/clock-in").json()["id"]
    at(client, START + timedelta(hours=16))
    assert client.post(PREFIX + "/overdue/confirm", json={"choice": "still_working"}).status_code == 200
    assert client.get(PREFIX + "/overdue").json()["suppressed_until"] is not None
    corrected_start = START + timedelta(hours=hours)
    response = edit(client, detail(client, record_id), None, clock_in_at=corrected_start.isoformat())
    assert response.status_code == 200
    overdue = client.get(PREFIX + "/overdue").json()
    assert overdue["record_id"] == record_id
    assert datetime.fromisoformat(overdue["overdue_at"]) == corrected_start + timedelta(hours=16)
    assert overdue["requires_confirmation"] is requires_confirmation
    assert overdue["suppressed_until"] is None
    assert overdue["last_choice"] is None
    assert client.get(PREFIX + "/status").json()["active_record"]["id"] == record_id


@pytest.mark.parametrize("close_shift", [False, True])
def test_confirmation_racing_correction_cannot_restore_stale_suppression(
    client, client_factory, close_shift,
):
    at(client, START)
    record_id = client.post(PREFIX + "/clock-in").json()["id"]
    record = detail(client, record_id)
    now = START + timedelta(hours=17)
    at(client, now)
    gate = Barrier(2)

    def correct():
        gate.wait(timeout=5)
        return edit(client, record, START + timedelta(hours=10) if close_shift else None,
                    clock_in_at=(START + timedelta(hours=2)).isoformat())

    with client_factory() as another:
        at(another, now)

        def confirm():
            gate.wait(timeout=5)
            return another.post(PREFIX + "/overdue/confirm", json={"choice": "still_working"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            correction = pool.submit(correct)
            confirmation = pool.submit(confirm)
            assert correction.result(timeout=15).status_code == 200
            assert confirmation.result(timeout=15).status_code in (200, 409)

    current = detail(client, record_id)
    assert current["is_modified"] is True
    overdue = client.get(PREFIX + "/overdue").json()
    assert overdue["requires_confirmation"] is False
    assert overdue["suppressed_until"] is None
    assert overdue["last_choice"] is None
    assert overdue["record_id"] == (None if close_shift else record_id)
    assert_audit_chain(client, record_id, ["clock_in", "update"])
