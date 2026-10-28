"""HTTP attendance endpoints; dependencies supply identity and clock."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app import attendance_service
from app.dependencies import get_clock, get_current_user_id
from app.schemas import AttendanceRecord, AttendanceStatus

router = APIRouter(prefix="/api/attendance", tags=["attendance"])
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
CurrentClock = Annotated[Callable[[], datetime], Depends(get_clock)]


@router.get("/status", response_model=AttendanceStatus)
def get_status(user_id: CurrentUserId) -> AttendanceStatus:
    return attendance_service.get_status(user_id)


@router.get("/history", response_model=list[AttendanceRecord])
def get_history(user_id: CurrentUserId) -> list[AttendanceRecord]:
    return attendance_service.get_history(user_id)


@router.post("/clock-in", response_model=AttendanceRecord, status_code=201)
def clock_in(user_id: CurrentUserId, clock: CurrentClock) -> AttendanceRecord:
    return attendance_service.clock_in(user_id, clock)


@router.post("/clock-out", response_model=AttendanceRecord)
def clock_out(user_id: CurrentUserId, clock: CurrentClock) -> AttendanceRecord:
    return attendance_service.clock_out(user_id, clock)
