"""Minimal FastAPI entry point for WBS 0.2."""

from fastapi import FastAPI

app = FastAPI(title="爆楽勤怠 API", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    """Return a small response for API connectivity checks."""
    return {"status": "ok"}
