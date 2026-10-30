"""Attendance HTTP endpoints; PostgreSQL engine, identity, and clock use Depends."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app import attendance_service
from app.dependencies import DatabaseEngine, get_clock, get_current_user_id
from app.schemas import AttendanceRecord, AttendanceStatus

router = APIRouter(prefix="/api/attendance", tags=["attendance"])
CurrentUserId = Annotated[int, Depends(get_current_user_id)]
CurrentClock = Annotated[Callable[[], datetime], Depends(get_clock)]


@router.get("/status", response_model=AttendanceStatus)
def get_status(engine: DatabaseEngine, user_id: CurrentUserId) -> AttendanceStatus:
    return attendance_service.get_status(engine, user_id)


@router.get("/history", response_model=list[AttendanceRecord])
def get_history(engine: DatabaseEngine, user_id: CurrentUserId) -> list[AttendanceRecord]:
    return attendance_service.get_history(engine, user_id)


@router.post("/clock-in", response_model=AttendanceRecord, status_code=201)
def clock_in(engine: DatabaseEngine, user_id: CurrentUserId, clock: CurrentClock) -> AttendanceRecord:
    return attendance_service.clock_in(engine, user_id, clock)


@router.post("/clock-out", response_model=AttendanceRecord)
def clock_out(engine: DatabaseEngine, user_id: CurrentUserId, clock: CurrentClock) -> AttendanceRecord:
    return attendance_service.clock_out(engine, user_id, clock)
