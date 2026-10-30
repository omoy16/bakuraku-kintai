"""Cancel only the user's latest punch within 60 seconds of its DB audit timestamp."""

from datetime import datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.attendance_service import lock_user, snapshot, write_audit
from app.exceptions import AttendanceConflictError, DatabaseUnavailableError
from app.models import AttendanceAuditLog as Audit, AttendanceRecord as Record
from app.postgres import api_session
from app.schemas import AttendanceCancellation

CANCELLATION_WINDOW = timedelta(seconds=60)
PUNCH_OPERATIONS = {"clock_in", "clock_out"}


def db_now(session: Session) -> datetime:
    """Use the database clock, not client time or the punch timestamp."""
    result = session.scalar(select(func.clock_timestamp()))
    if result is None:
        raise DatabaseUnavailableError()
    return result


def cancel_latest_punch(engine: Engine, user_id: int) -> AttendanceCancellation:
    """Reverse one latest punch; save its before/after audit in the same transaction."""
    with api_session(engine) as session:
        # Keep the WBS 1.4 lock order: user first, then attendance record.
        lock_user(session, user_id)
        latest = session.scalar(
            select(Audit)
            .join(Record, Audit.attendance_record_id == Record.id)
            .where(Record.user_id == user_id)
            .order_by(Audit.id.desc())
            .limit(1)
        )
        # A cancel, update, or missing audit is never itself undoable.
        if latest is None or latest.operation not in PUNCH_OPERATIONS:
            raise AttendanceConflictError("No cancellable punch")

        row = session.scalar(
            select(Record)
            .where(Record.id == latest.attendance_record_id, Record.user_id == user_id)
            .with_for_update()
        )
        if row is None:
            raise AttendanceConflictError("No cancellable punch")

        now = db_now(session)
        elapsed = now - latest.operated_at
        if not timedelta(0) <= elapsed <= CANCELLATION_WINDOW:
            raise AttendanceConflictError("Cancellation window expired")

        before = snapshot(row)
        if latest.operation == "clock_in":
            if row.cancelled_at is not None or row.clock_out_at is not None:
                raise AttendanceConflictError("Punch state has changed")
            # Cancel the entire shift without deleting either the record or audit.
            row.cancelled_at = now
            operation = "cancel_clock_in"
            status = "not_working"
        else:
            if row.cancelled_at is not None or row.clock_out_at is None:
                raise AttendanceConflictError("Punch state has changed")
            # Cancel only the clock-out; the original clock-in remains active.
            row.clock_out_at = None
            operation = "cancel_clock_out"
            status = "working"

        row.updated_at = now
        write_audit(session, row, operation, before)
        # api_session commits before the HTTP handler receives this result.
        return AttendanceCancellation(
            record_id=row.id, cancelled_operation=latest.operation, status=status,
        )
