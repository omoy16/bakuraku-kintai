"""API liveness and PostgreSQL connectivity, independent of the demo identity."""

from fastapi import APIRouter

from app.dependencies import DatabaseEngine
from app.postgres import check_database
from app.schemas import DatabaseHealthStatus, HealthStatus

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/db", response_model=DatabaseHealthStatus)
def database_health(engine: DatabaseEngine) -> DatabaseHealthStatus:
    check_database(engine)
    return DatabaseHealthStatus(status="ok", database="postgresql")
