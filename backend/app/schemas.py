"""API response models; SQLAlchemy table models live in models.py."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AttendanceRecord(BaseModel):
    id: int
    user_id: int
    clock_in_at: datetime
    clock_out_at: datetime | None


class AttendanceCancellation(BaseModel):
    record_id: int
    cancelled_operation: Literal["clock_in", "clock_out"]
    status: Literal["not_working", "working"]


class AttendanceStatus(BaseModel):
    user_id: int
    status: Literal["not_working", "working"]
    active_record: AttendanceRecord | None


class HealthStatus(BaseModel):
    status: Literal["ok"]


class DatabaseHealthStatus(HealthStatus):
    database: Literal["postgresql"]
