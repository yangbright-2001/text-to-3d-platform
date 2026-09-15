"""FastAPI application entrypoint.

M1 provides only the app skeleton and a health endpoint. Routers, persistence,
Meshy integration and background task tracking are added in later milestones.
"""

from fastapi import FastAPI

from .config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)


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
