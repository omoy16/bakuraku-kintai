"""PostgreSQL connection and transaction helpers; no connection at import time."""

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, IntegrityError, TimeoutError
from sqlalchemy.orm import Session

from app.exceptions import AttendanceConflictError, DatabaseUnavailableError


def get_database_url(value: str | URL | None = None) -> URL:
    """Require an explicit PostgreSQL target and use the psycopg 3 driver."""
    if value is None:
        value = os.environ.get("BAKURAKU_DATABASE_URL", "")
    if not value:
        raise ValueError("BAKURAKU_DATABASE_URL must be set for PostgreSQL commands")
    try:
        url = make_url(value)
    except ArgumentError:
        raise ValueError("Invalid PostgreSQL database URL") from None
    if url.drivername not in ("postgresql", "postgresql+psycopg"):
        raise ValueError("Use a postgresql+psycopg:// database URL")
    return url.set(drivername="postgresql+psycopg")


def create_db_engine(value: str | URL | None = None) -> Engine:
    """Create a lazy engine with UTC sessions and no SQL parameter logging."""
    url = get_database_url(value)
    options = url.query.get("options", "")
    if not isinstance(options, str):
        raise ValueError("Database URL must contain at most one options parameter")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=5,
        isolation_level="READ COMMITTED",
        hide_parameters=True,
        connect_args={"options": f"{options} -c timezone=UTC".strip(), "connect_timeout": 5},
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit attendance and audit changes together; roll back and close on error."""
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            yield session


@contextmanager
def api_session(engine: Engine) -> Iterator[Session]:
    """Translate known DB failures only after the transaction has rolled back.

    A response is returned by the service only after commit succeeds. An audit
    failure must not be mistaken for a duplicate punch or leave a partial write.
    """
    try:
        with session_scope(engine) as session:
            yield session
    except IntegrityError as exc:
        state = getattr(exc.orig, "sqlstate", None)
        name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        conflicts = {
            ("23505", "uq_attendance_active_user"): "Already working",
            ("23P01", "ex_attendance_overlap"): "Attendance period overlaps existing record",
            ("23514", "ck_attendance_time_order"): "Clock is earlier than clock-in time",
        }
        detail = conflicts.get((state, name))
        if detail is not None:
            raise AttendanceConflictError(detail) from None
        raise DatabaseUnavailableError() from None
    except (DBAPIError, TimeoutError):
        raise DatabaseUnavailableError() from None


def check_database(engine: Engine) -> None:
    """Connectivity check; migrations and demo provisioning are separate steps."""
    with api_session(engine) as session:
        session.execute(text("SELECT 1"))
