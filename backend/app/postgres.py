"""PostgreSQL connection and transaction helpers; no connection at import time."""

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session


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
        hide_parameters=True,
        connect_args={"options": f"{options} -c timezone=UTC".strip()},
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit attendance and audit changes together; roll back and close on error."""
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            yield session
