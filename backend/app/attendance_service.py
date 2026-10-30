"""PostgreSQL attendance operations: serialize per user and save audit atomically."""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.exceptions import AttendanceConflictError, DatabaseUnavailableError
from app.models import AttendanceAuditLog, AttendanceRecord as Record, User
from app.postgres import api_session
from app.schemas import AttendanceRecord, AttendanceStatus


def active_record(session: Session, user_id: int, *, lock: bool = False) -> Record | None:
    # No date filter: overnight and long-running shifts stay active.
    statement = select(Record).where(
        Record.user_id == user_id, Record.cancelled_at.is_(None),
        Record.clock_out_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    return session.scalar(statement)


def lock_user(session: Session, user_id: int) -> None:
    # An active attendance row might not exist yet. Lock the stable parent first.
    # All attendance writes must acquire locks in this order: user -> attendance.
    found = session.scalar(select(User.id).where(User.id == user_id).with_for_update())
    if found is None:
        raise DatabaseUnavailableError()


def as_record(row: Record) -> AttendanceRecord:
    return AttendanceRecord(
        id=row.id, user_id=row.user_id,
        clock_in_at=row.clock_in_at.astimezone(timezone.utc),
        clock_out_at=(row.clock_out_at.astimezone(timezone.utc)
                      if row.clock_out_at is not None else None),
    )


def snapshot(row: Record) -> dict:
    return {
        key: value.astimezone(timezone.utc).isoformat() if value is not None else None
        for key, value in (
            ("clock_in_at", row.clock_in_at),
            ("clock_out_at", row.clock_out_at),
            ("cancelled_at", row.cancelled_at),
        )
    }


def write_audit(session: Session, row: Record, operation: str, before: dict | None) -> None:
    session.add(AttendanceAuditLog(
        attendance_record_id=row.id, actor_user_id=row.user_id, operation=operation,
        before_values=before, after_values=snapshot(row),
    ))
    # Check both attendance and audit writes before building the success response.
    session.flush()


def get_status(engine: Engine, user_id: int) -> AttendanceStatus:
    with api_session(engine) as session:
        row = active_record(session, user_id)
        return AttendanceStatus(
            user_id=user_id, status="working" if row is not None else "not_working",
            active_record=as_record(row) if row is not None else None,
        )


def get_history(engine: Engine, user_id: int) -> list[AttendanceRecord]:
    with api_session(engine) as session:
        rows = session.scalars(
            select(Record).where(Record.user_id == user_id, Record.cancelled_at.is_(None))
            .order_by(Record.clock_in_at.desc(), Record.id.desc())
        ).all()
        return [as_record(row) for row in rows]


def clock_in(engine: Engine, user_id: int, clock: Callable[[], datetime]) -> AttendanceRecord:
    with api_session(engine) as session:
        lock_user(session, user_id)
        if active_record(session, user_id, lock=True) is not None:
            raise AttendanceConflictError("Already working")
        row = Record(user_id=user_id, clock_in_at=clock())
        session.add(row)
        session.flush()
        write_audit(session, row, "clock_in", None)
        return as_record(row)


def clock_out(engine: Engine, user_id: int, clock: Callable[[], datetime]) -> AttendanceRecord:
    with api_session(engine) as session:
        lock_user(session, user_id)
        row = active_record(session, user_id, lock=True)
        if row is None:
            raise AttendanceConflictError("Not working")
        now = clock()
        if now < row.clock_in_at:
            raise AttendanceConflictError("Clock is earlier than clock-in time")
        before = snapshot(row)
        row.clock_out_at = now
        row.updated_at = func.clock_timestamp()
        write_audit(session, row, "clock_out", before)
        return as_record(row)
