"""Request dependencies for a local demo; JWT verification belongs to WBS 3.x."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, select

from app.exceptions import DatabaseUnavailableError
from app.models import User
from app.postgres import api_session
from app.seed_demo_user import DEMO_COGNITO_SUB


def get_db_engine(request: Request) -> Engine:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise DatabaseUnavailableError()
    return engine


DatabaseEngine = Annotated[Engine, Depends(get_db_engine)]


def get_current_user_id(engine: DatabaseEngine) -> int:
    """Resolve only the explicitly seeded demo user; never create or guess an ID."""
    with api_session(engine) as session:
        user_id = session.scalar(select(User.id).where(User.cognito_sub == DEMO_COGNITO_SUB))
        if user_id is None:
            raise DatabaseUnavailableError()
        return user_id


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_clock() -> Callable[[], datetime]:
    """The service reads this clock only after acquiring the user's write lock."""
    return utc_now
