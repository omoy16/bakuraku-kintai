"""Translate known service errors into the existing public API contract."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import AttendanceConflictError, AttendanceNotFoundError, DatabaseUnavailableError


async def attendance_conflict_handler(
    request: Request, exc: AttendanceConflictError,
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


async def database_unavailable_handler(
    request: Request, exc: DatabaseUnavailableError,
) -> JSONResponse:
    # Never send SQL, paths, credentials, or the original exception to clients.
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


async def attendance_not_found_handler(
    request: Request, exc: AttendanceNotFoundError,
) -> JSONResponse:
    # The same response for unknown IDs and records owned by another user.
    return JSONResponse(status_code=404, content={"detail": "Attendance record not found"})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AttendanceConflictError, attendance_conflict_handler)
    app.add_exception_handler(AttendanceNotFoundError, attendance_not_found_handler)
    app.add_exception_handler(DatabaseUnavailableError, database_unavailable_handler)
