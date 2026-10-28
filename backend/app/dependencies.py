"""Request dependencies; JWT authentication belongs to WBS 3.x."""

from collections.abc import Callable
from datetime import datetime, timezone


def get_current_user_id() -> str:
    """Supply the fixed demo identity, never a client-provided user ID."""
    return "demo-user"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_clock() -> Callable[[], datetime]:
    """Supply a clock, so the service reads time after acquiring its write lock."""
    return utc_now
