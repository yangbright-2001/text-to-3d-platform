"""FastAPI application entrypoint.

M1 shipped the app skeleton and health endpoint; M2 adds SQLite persistence
initialization via the lifespan. Routers, Meshy integration and background
task tracking are added in later milestones.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the data directory and DB tables on startup (idempotent)."""
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check used to verify the backend is running and configured.

    Reports whether a Meshy API key is present without ever returning the key
    itself, so this is safe to expose to the frontend.
    """
    return {
        "status": "ok",
        "app": settings.app_name,
        "meshy_key_configured": "true" if settings.meshy_api_key else "false",
    }
