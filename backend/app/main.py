"""FastAPI entry point with local development connectivity checks."""

import sqlite3

from fastapi import FastAPI, HTTPException

from app.attendance import router as attendance_router
from app.database import connect_db

app = FastAPI(title="爆楽勤怠 API", version="0.1.0")
app.include_router(attendance_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Return a small response for API connectivity checks."""
    return {"status": "ok"}


@app.get("/api/health/db")
def database_health() -> dict[str, str]:
    """Check local database connectivity separately from API liveness."""
    try:
        with connect_db() as connection:
            connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except (sqlite3.Error, OSError, ValueError):
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ok", "database": "sqlite"}
