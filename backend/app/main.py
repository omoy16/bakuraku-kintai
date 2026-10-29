"""FastAPI composition: register routers and common error handlers."""

from fastapi import FastAPI

from app.exception_handlers import register_exception_handlers
from app.routers.attendance import router as attendance_router
from app.routers.health import router as health_router

app = FastAPI(title="爆楽勤怠 API", version="0.1.0")
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(attendance_router)
