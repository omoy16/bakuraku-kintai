"""Attendance PoC for one fixed demo user; authentication is added in WBS 3.x."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import connect_db

DEMO_USER_ID = "demo-user"
router = APIRouter(prefix="/api/attendance", tags=["attendance"])


class AttendanceRecord(BaseModel):
    id: int
    user_id: str
    clock_in_at: datetime
    clock_out_at: datetime | None


class AttendanceStatus(BaseModel):
    user_id: str
    status: Literal["not_working", "working"]
    active_record: AttendanceRecord | None


def utc_now() -> datetime:
    """Use the server clock; clients cannot select the user or punch time."""
    return datetime.now(timezone.utc)


@contextmanager
def attendance_db() -> Iterator[sqlite3.Connection]:
    try:
        with connect_db() as connection:
            yield connection
    except (sqlite3.Error, OSError, ValueError):
        # Do not expose SQL, DB paths, or environment settings in API responses.
        raise HTTPException(status_code=503, detail="Database unavailable") from None


def active_record(connection: sqlite3.Connection) -> sqlite3.Row | None:
    # Deliberately no date filter: overnight and long-running shifts stay active.
    return connection.execute(
        "SELECT * FROM attendance_records WHERE user_id = ? AND clock_out_at IS NULL",
        (DEMO_USER_ID,),
    ).fetchone()


def as_record(row: sqlite3.Row) -> AttendanceRecord:
    return AttendanceRecord(**dict(row))


@router.get("/status", response_model=AttendanceStatus)
def get_status() -> AttendanceStatus:
    with attendance_db() as connection:
        row = active_record(connection)
        return AttendanceStatus(
            user_id=DEMO_USER_ID,
            status="working" if row is not None else "not_working",
            active_record=as_record(row) if row is not None else None,
        )


@router.get("/history", response_model=list[AttendanceRecord])
def get_history() -> list[AttendanceRecord]:
    """Return the demo user's punches, newest shift first."""
    with attendance_db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM attendance_records
            WHERE user_id = ?
            ORDER BY clock_in_at DESC, id DESC
            """,
            (DEMO_USER_ID,),
        ).fetchall()
        return [as_record(row) for row in rows]


@router.post("/clock-in", response_model=AttendanceRecord, status_code=201)
def clock_in() -> AttendanceRecord:
    with attendance_db() as connection:
        # Serialize the state check and write, including concurrent requests.
        connection.execute("BEGIN IMMEDIATE")
        if active_record(connection) is not None:
            raise HTTPException(status_code=409, detail="Already working")
        timestamp = utc_now().isoformat(timespec="microseconds")
        cursor = connection.execute(
            "INSERT INTO attendance_records (user_id, clock_in_at) VALUES (?, ?)",
            (DEMO_USER_ID, timestamp),
        )
        row = connection.execute(
            "SELECT * FROM attendance_records WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return as_record(row)


@router.post("/clock-out", response_model=AttendanceRecord)
def clock_out() -> AttendanceRecord:
    with attendance_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = active_record(connection)
        if row is None:
            raise HTTPException(status_code=409, detail="Not working")
        now = utc_now()
        if now < datetime.fromisoformat(row["clock_in_at"]):
            raise HTTPException(status_code=409, detail="Clock is earlier than clock-in time")
        connection.execute(
            "UPDATE attendance_records SET clock_out_at = ? WHERE id = ?",
            (now.isoformat(timespec="microseconds"), row["id"]),
        )
        updated = connection.execute(
            "SELECT * FROM attendance_records WHERE id = ?", (row["id"],)
        ).fetchone()
        return as_record(updated)
