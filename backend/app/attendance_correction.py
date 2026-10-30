"""WBS 1.7: owner-scoped records, optimistic edits and append-only audit history."""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import Engine, func, select
from app.attendance_service import as_record, lock_user, snapshot, write_audit
from app.exceptions import AttendanceConflictError, AttendanceNotFoundError
from app.models import AttendanceAuditLog as Audit, AttendanceRecord as Record
from app.postgres import api_session
from app.schemas import AttendanceAuditEntry, AttendanceCorrectionRequest, AttendanceDetail


def record_statement(user_id: int):
    # Fetch the values and revision in ONE statement. Two SELECTs at READ COMMITTED
    # could pair old timestamps with a new revision, allowing a later lost update.
    latest_id = (
        select(Audit.id).where(Audit.attendance_record_id == Record.id)
        .order_by(Audit.id.desc()).limit(1).correlate(Record).scalar_subquery()
    )
    modified = (
        select(Audit.id).where(
            Audit.attendance_record_id == Record.id, Audit.operation == "update",
        ).correlate(Record).exists()
    )
    return select(Record, latest_id, modified).where(Record.user_id == user_id)


def as_detail(row: Record, latest_id: int | None, modified: bool) -> AttendanceDetail:
    return AttendanceDetail(
        **as_record(row).model_dump(),
        cancelled_at=(row.cancelled_at.astimezone(timezone.utc)
                      if row.cancelled_at is not None else None),
        is_modified=modified, latest_operation_id=latest_id,
    )


def get_records(engine: Engine, user_id: int) -> list[AttendanceDetail]:
    """Normal history with correction metadata; legacy /history keeps its shape."""
    with api_session(engine) as session:
        rows = session.execute(
            record_statement(user_id).where(Record.cancelled_at.is_(None))
            .order_by(Record.clock_in_at.desc(), Record.id.desc())
        ).all()
        return [as_detail(*row) for row in rows]


def get_record(engine: Engine, user_id: int, record_id: int) -> AttendanceDetail:
    with api_session(engine) as session:
        result = session.execute(
            record_statement(user_id).where(Record.id == record_id),
        ).one_or_none()
        if result is None:
            raise AttendanceNotFoundError()
        return as_detail(*result)


def get_audit_logs(engine: Engine, user_id: int, record_id: int) -> list[AttendanceAuditEntry]:
    with api_session(engine) as session:
        owned = session.scalar(select(Record.id).where(
            Record.id == record_id, Record.user_id == user_id,
        ))
        if owned is None:
            raise AttendanceNotFoundError()
        rows = session.scalars(
            select(Audit).where(Audit.attendance_record_id == record_id)
            .order_by(Audit.operated_at.desc(), Audit.id.desc())
        ).all()
        return [AttendanceAuditEntry(
            id=row.id, attendance_record_id=row.attendance_record_id,
            actor_user_id=row.actor_user_id, operation=row.operation,
            before_values=row.before_values, after_values=row.after_values,
            change_reason=row.change_reason,
            operated_at=row.operated_at.astimezone(timezone.utc),
        ) for row in rows]


def correct_record(
    engine: Engine, user_id: int, record_id: int, payload: AttendanceCorrectionRequest,
    clock: Callable[[], datetime],
) -> AttendanceDetail:
    with api_session(engine) as session:
        # Shared lock order serializes corrections with punches, cancels and confirms.
        lock_user(session, user_id)
        row = session.scalar(select(Record).where(
            Record.id == record_id, Record.user_id == user_id,
        ).with_for_update())
        if row is None:
            raise AttendanceNotFoundError()
        if row.cancelled_at is not None:
            raise AttendanceConflictError("Cancelled attendance cannot be corrected")
        latest_id = session.scalar(
            select(Audit.id).where(Audit.attendance_record_id == record_id)
            .order_by(Audit.id.desc()).limit(1),
        )
        if payload.expected_operation_id != latest_id:
            raise AttendanceConflictError("Attendance has changed; reload before correcting")

        start = payload.clock_in_at.astimezone(timezone.utc)
        end = payload.clock_out_at.astimezone(timezone.utc) if payload.clock_out_at else None
        now = clock()
        if start > now or (end is not None and end > now):
            raise AttendanceConflictError("Attendance time cannot be in the future")
        if start == row.clock_in_at and end == row.clock_out_at:
            raise AttendanceConflictError("Attendance times are unchanged")

        before = snapshot(row)
        row.clock_in_at = start
        row.clock_out_at = end
        # Prior acknowledgement referred to the old times. Notification success
        # (reminder_sent_at) remains intact so an edit never sends a second notice.
        row.overdue_confirmed_at = None
        row.overdue_confirmed_choice = None
        row.updated_at = func.clock_timestamp()
        write_audit(session, row, "update", before, change_reason=payload.change_reason)
        latest_id = session.scalar(
            select(Audit.id).where(Audit.attendance_record_id == record_id)
            .order_by(Audit.id.desc()).limit(1),
        )
        # Both the edit and audit must commit before this result reaches HTTP.
        return as_detail(row, latest_id, True)
