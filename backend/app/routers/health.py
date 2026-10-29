"""Liveness and SQLite readiness, independent of attendance identity."""

from fastapi import APIRouter

from app.database import check_database
from app.schemas import DatabaseHealthStatus, HealthStatus

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/db", response_model=DatabaseHealthStatus)
def database_health() -> DatabaseHealthStatus:
    check_database()
    return DatabaseHealthStatus(status="ok", database="sqlite")
