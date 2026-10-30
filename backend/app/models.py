"""PostgreSQL schema agreed in WBS 1.1 / Issue #8, including change_reason."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("cognito_sub", name="uq_users_cognito_sub"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    cognito_sub: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_attendance_user", ondelete="RESTRICT")
    )
    clock_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overdue_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overdue_confirmed_choice: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        CheckConstraint(
            "overdue_confirmed_choice IS NULL OR "
            "overdue_confirmed_choice IN ('still_working', 'forgot_clock_out')",
            name="ck_attendance_overdue_choice",
        ),
        CheckConstraint(
            "(overdue_confirmed_at IS NULL) = (overdue_confirmed_choice IS NULL)",
            name="ck_attendance_overdue_fields",
        ),
        CheckConstraint(
            "clock_out_at IS NULL OR clock_out_at >= clock_in_at",
            name="ck_attendance_time_order",
        ),
        Index(
            "uq_attendance_active_user",
            user_id,
            unique=True,
            postgresql_where=text("clock_out_at IS NULL AND cancelled_at IS NULL"),
        ),
        ExcludeConstraint(
            (user_id, "="),
            (func.tstzrange(clock_in_at, clock_out_at, literal_column("'[)'")), "&&"),
            name="ex_attendance_overlap",
            using="gist",
            where=text("cancelled_at IS NULL"),
        ),
        Index(
            "ix_attendance_user_history",
            user_id,
            clock_in_at.desc(),
            id.desc(),
            postgresql_where=text("cancelled_at IS NULL"),
        ),
    )


class AttendanceAuditLog(Base):
    __tablename__ = "attendance_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    attendance_record_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("attendance_records.id", name="fk_audit_attendance", ondelete="RESTRICT"),
    )
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_audit_actor", ondelete="RESTRICT")
    )
    operation: Mapped[str] = mapped_column(String(32))
    # None must be SQL NULL, not a JSON null value, for the first clock-in.
    before_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    after_values: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True))
    change_reason: Mapped[str | None] = mapped_column(Text)
    operated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        CheckConstraint(
            "operation IN ('clock_in', 'clock_out', 'update', "
            "'cancel_clock_in', 'cancel_clock_out')",
            name="ck_audit_operation",
        ),
        Index("ix_audit_record_history", attendance_record_id, operated_at.desc(), id.desc()),
    )
