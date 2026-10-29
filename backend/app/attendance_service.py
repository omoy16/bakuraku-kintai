"""Attendance operations; PostgreSQL switching belongs to WBS 1.4."""

import sqlite3
from collections.abc import Callable
from datetime import datetime

from app.database import api_connection
from app.exceptions import AttendanceConflictError
from app.schemas import AttendanceRecord, AttendanceStatus


def active_record(connection: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    # Deliberately no date filter: overnight and long-running shifts stay active.
    return connection.execute(
        "SELECT * FROM attendance_records WHERE user_id = ? AND clock_out_at IS NULL",
        (user_id,),
    ).fetchone()


def as_record(row: sqlite3.Row) -> AttendanceRecord:
    return AttendanceRecord(**dict(row))


def get_status(user_id: str) -> AttendanceStatus:
    with api_connection() as connection:
        row = active_record(connection, user_id)
        return AttendanceStatus(
            user_id=user_id,
            status="working" if row is not None else "not_working",
            active_record=as_record(row) if row is not None else None,
        )


def get_history(user_id: str) -> list[AttendanceRecord]:
    """Return the demo user's punches, newest shift first."""
    with api_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM attendance_records
            WHERE user_id = ?
            ORDER BY clock_in_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
        return [as_record(row) for row in rows]


def clock_in(user_id: str, clock: Callable[[], datetime]) -> AttendanceRecord:
    with api_connection() as connection:
        # Serialize the state check and write, including concurrent requests.
        connection.execute("BEGIN IMMEDIATE")
        if active_record(connection, user_id) is not None:
            raise AttendanceConflictError("Already working")
        timestamp = clock().isoformat(timespec="microseconds")
        cursor = connection.execute(
            "INSERT INTO attendance_records (user_id, clock_in_at) VALUES (?, ?)",
            (user_id, timestamp),
        )
        row = connection.execute(
            "SELECT * FROM attendance_records WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return as_record(row)


def clock_out(user_id: str, clock: Callable[[], datetime]) -> AttendanceRecord:
    with api_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = active_record(connection, user_id)
        if row is None:
            raise AttendanceConflictError("Not working")
        now = clock()
        if now < datetime.fromisoformat(row["clock_in_at"]):
            raise AttendanceConflictError("Clock is earlier than clock-in time")
        connection.execute(
            "UPDATE attendance_records SET clock_out_at = ? WHERE id = ?",
            (now.isoformat(timespec="microseconds"), row["id"]),
        )
        updated = connection.execute(
            "SELECT * FROM attendance_records WHERE id = ?", (row["id"],)
        ).fetchone()
        return as_record(updated)
