"""Create the three PostgreSQL tables and attendance integrity constraints.

Revision ID: 0001_attendance_schema
Revises: None
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_attendance_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Shared extension: retain it on downgrade, as other applications may use it.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public")
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("cognito_sub", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.UniqueConstraint("cognito_sub", name="uq_users_cognito_sub"),
    )
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name="fk_attendance_user", ondelete="RESTRICT"),
        sa.CheckConstraint("clock_out_at IS NULL OR clock_out_at >= clock_in_at",
                           name="ck_attendance_time_order"),
        postgresql.ExcludeConstraint(
            ("user_id", "="),
            (sa.text("tstzrange(clock_in_at, clock_out_at, '[)')"), "&&"),
            name="ex_attendance_overlap", using="gist",
            where=sa.text("cancelled_at IS NULL"),
        ),
    )
    op.create_index(
        "uq_attendance_active_user", "attendance_records", ["user_id"], unique=True,
        postgresql_where=sa.text("clock_out_at IS NULL AND cancelled_at IS NULL"),
    )
    op.create_index(
        "ix_attendance_user_history", "attendance_records",
        ["user_id", sa.text("clock_in_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )
    op.create_table(
        "attendance_audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("attendance_record_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("before_values", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("after_values", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("operated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.ForeignKeyConstraint(["attendance_record_id"], ["attendance_records.id"],
                                name="fk_audit_attendance", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"],
                                name="fk_audit_actor", ondelete="RESTRICT"),
        sa.CheckConstraint(
            "operation IN ('clock_in', 'clock_out', 'update', "
            "'cancel_clock_in', 'cancel_clock_out')", name="ck_audit_operation",
        ),
    )
    op.create_index(
        "ix_audit_record_history", "attendance_audit_logs",
        ["attendance_record_id", sa.text("operated_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_table("attendance_audit_logs")
    op.drop_table("attendance_records")
    op.drop_table("users")
