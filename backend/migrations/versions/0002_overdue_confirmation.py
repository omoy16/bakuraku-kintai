"""Persist long-running shift confirmation separately from SNS notifications.

Revision ID: 0002_overdue_confirmation
Revises: 0001_attendance_schema
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_overdue_confirmation"
down_revision = "0001_attendance_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance_records", sa.Column(
        "overdue_confirmed_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("attendance_records", sa.Column(
        "overdue_confirmed_choice", sa.String(32), nullable=True,
    ))
    op.create_check_constraint(
        "ck_attendance_overdue_choice", "attendance_records",
        "overdue_confirmed_choice IS NULL OR "
        "overdue_confirmed_choice IN ('still_working', 'forgot_clock_out')",
    )
    op.create_check_constraint(
        "ck_attendance_overdue_fields", "attendance_records",
        "(overdue_confirmed_at IS NULL) = (overdue_confirmed_choice IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_attendance_overdue_fields", "attendance_records", type_="check")
    op.drop_constraint("ck_attendance_overdue_choice", "attendance_records", type_="check")
    op.drop_column("attendance_records", "overdue_confirmed_choice")
    op.drop_column("attendance_records", "overdue_confirmed_at")
