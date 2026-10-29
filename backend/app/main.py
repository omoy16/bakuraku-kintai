"""FastAPI composition and application-scoped PostgreSQL engine lifecycle."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.exception_handlers import register_exception_handlers
from app.postgres import create_db_engine
from app.routers.attendance import router as attendance_router
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Engine creation is lazy: it does not connect, migrate, or seed.
    # Liveness remains available without DB configuration; readiness returns 503.
    try:
        app.state.db_engine = create_db_engine()
    except ValueError:
        app.state.db_engine = None
    try:
        yield
    finally:
        if app.state.db_engine is not None:
            app.state.db_engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(title="爆楽勤怠 API", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(attendance_router)
    return application


app = create_app()
