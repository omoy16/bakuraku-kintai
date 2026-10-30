"""API response models; SQLAlchemy table models live in models.py."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints,
    field_validator, model_validator,
)


class AttendanceRecord(BaseModel):
    id: int
    user_id: int
    clock_in_at: datetime
    clock_out_at: datetime | None


class AttendanceDetail(AttendanceRecord):
    cancelled_at: datetime | None
    is_modified: bool
    latest_operation_id: int | None


class AttendanceSnapshot(BaseModel):
    clock_in_at: datetime
    clock_out_at: datetime | None
    cancelled_at: datetime | None


class AttendanceAuditEntry(BaseModel):
    id: int
    attendance_record_id: int
    actor_user_id: int
    operation: Literal["clock_in", "clock_out", "update", "cancel_clock_in", "cancel_clock_out"]
    before_values: AttendanceSnapshot | None
    after_values: AttendanceSnapshot
    change_reason: str | None
    operated_at: datetime


class AttendanceCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Both fields are required: an explicit null reopens a completed shift.
    clock_in_at: AwareDatetime
    clock_out_at: AwareDatetime | None
    expected_operation_id: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)] | None
    change_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]

    @field_validator("clock_in_at", "clock_out_at", mode="before")
    @classmethod
    def require_datetime_input(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("Use a timezone-aware ISO 8601 datetime")
        return value

    @model_validator(mode="after")
    def validate_time_order(self) -> Self:
        if self.clock_out_at is not None and self.clock_out_at < self.clock_in_at:
            raise ValueError("Clock-out must be at or after clock-in")
        return self


class AttendanceCancellation(BaseModel):
    record_id: int
    cancelled_operation: Literal["clock_in", "clock_out"]
    status: Literal["not_working", "working"]


class AttendanceStatus(BaseModel):
    user_id: int
    status: Literal["not_working", "working"]
    active_record: AttendanceRecord | None


class OverdueStatus(BaseModel):
    record_id: int | None
    overdue_at: datetime | None
    requires_confirmation: bool
    suppressed_until: datetime | None
    last_choice: Literal["still_working", "forgot_clock_out"] | None


class OverdueConfirmationRequest(BaseModel):
    choice: Literal["still_working", "forgot_clock_out"]


class OverdueConfirmation(BaseModel):
    record_id: int
    choice: Literal["still_working", "forgot_clock_out"]
    requires_correction: bool
    suppressed_until: datetime


class HealthStatus(BaseModel):
    status: Literal["ok"]


class DatabaseHealthStatus(HealthStatus):
    database: Literal["postgresql"]
