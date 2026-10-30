"""WBS 1.6: server-owned overdue evaluation and durable confirmation cooldown."""

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Engine, func

from app.attendance_service import active_record, lock_user
from app.exceptions import AttendanceConflictError
from app.models import AttendanceRecord as Record
from app.postgres import api_session
from app.schemas import OverdueConfirmation, OverdueStatus

OVERDUE_AFTER = timedelta(hours=16)
CONFIRMATION_SNOOZE = timedelta(hours=1)
CHOICES = ("still_working", "forgot_clock_out")


def evaluate_overdue(row: Record | None, now: datetime) -> OverdueStatus:
    """Evaluate at the 16h/1h boundaries without mutating state."""
    if row is None:
        return OverdueStatus(
            record_id=None, overdue_at=None, requires_confirmation=False,
            suppressed_until=None, last_choice=None,
        )
    overdue_at = row.clock_in_at + OVERDUE_AFTER
    suppressed_until = (
        row.overdue_confirmed_at + CONFIRMATION_SNOOZE
        if row.overdue_confirmed_at is not None else None
    )
    return OverdueStatus(
        record_id=row.id,
        overdue_at=overdue_at,
        requires_confirmation=now >= overdue_at
        and (suppressed_until is None or now >= suppressed_until),
        suppressed_until=suppressed_until,
        last_choice=row.overdue_confirmed_choice,
    )


def get_overdue(engine: Engine, user_id: int, clock: Callable[[], datetime]) -> OverdueStatus:
    """Status is per current user and current active shift, never a calendar day."""
    with api_session(engine) as session:
        row = active_record(session, user_id)
        return evaluate_overdue(row, clock())


def confirm_overdue(
    engine: Engine, user_id: int, choice: str, clock: Callable[[], datetime],
) -> OverdueConfirmation:
    """Acknowledge an overdue shift; never close or correct it automatically."""
    if choice not in CHOICES:
        raise ValueError("Invalid overdue confirmation choice")
    with api_session(engine) as session:
        # WBS 1.4 ordering: lock the user before the active attendance row.
        lock_user(session, user_id)
        row = active_record(session, user_id, lock=True)
        if row is None:
            raise AttendanceConflictError("Not working")
        now = clock()
        if now < row.clock_in_at + OVERDUE_AFTER:
            raise AttendanceConflictError("Shift is not overdue")
        if row.overdue_confirmed_at is not None:
            if now < row.overdue_confirmed_at:
                raise AttendanceConflictError("Clock is earlier than last confirmation")
            if now < row.overdue_confirmed_at + CONFIRMATION_SNOOZE:
                if row.overdue_confirmed_choice != choice:
                    raise AttendanceConflictError("Confirmation already handled")
                # An identical retry does not reset the cooldown.
                return OverdueConfirmation(
                    record_id=row.id, choice=choice,
                    requires_correction=choice == "forgot_clock_out",
                    suppressed_until=row.overdue_confirmed_at + CONFIRMATION_SNOOZE,
                )
        row.overdue_confirmed_at = now
        row.overdue_confirmed_choice = choice
        row.updated_at = func.clock_timestamp()
        session.flush()
        # "forgot_clock_out" requires later manual correction (WBS 1.7).
        return OverdueConfirmation(
            record_id=row.id, choice=choice,
            requires_correction=choice == "forgot_clock_out",
            suppressed_until=now + CONFIRMATION_SNOOZE,
        )
