"""Attendance HTTP endpoints; PostgreSQL engine, identity, and clock use Depends."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app import attendance_cancellation, attendance_overdue, attendance_service
from app.dependencies import DatabaseEngine, get_clock, get_current_user_id
from app.schemas import (
    AttendanceCancellation, AttendanceRecord, AttendanceStatus,
    OverdueConfirmation, OverdueConfirmationRequest, OverdueStatus,
)

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


@router.post("/cancel", response_model=AttendanceCancellation)
def cancel_latest_punch(engine: DatabaseEngine, user_id: CurrentUserId) -> AttendanceCancellation:
    return attendance_cancellation.cancel_latest_punch(engine, user_id)


@router.get("/overdue", response_model=OverdueStatus)
def get_overdue(engine: DatabaseEngine, user_id: CurrentUserId, clock: CurrentClock) -> OverdueStatus:
    return attendance_overdue.get_overdue(engine, user_id, clock)


@router.post("/overdue/confirm", response_model=OverdueConfirmation)
def confirm_overdue(
    payload: OverdueConfirmationRequest, engine: DatabaseEngine,
    user_id: CurrentUserId, clock: CurrentClock,
) -> OverdueConfirmation:
    return attendance_overdue.confirm_overdue(engine, user_id, payload.choice, clock)
