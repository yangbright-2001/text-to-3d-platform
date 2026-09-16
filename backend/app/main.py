"""FastAPI application entrypoint.

Wires together config, persistence, the Meshy client, and the generations
router. All process-scoped resources (shared ``MeshyClient``, session factory,
background-task registry) live on ``app.state`` so watchers spawned by the
endpoint layer can pick them up without going through FastAPI's request DI.
"""

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

# Register 3D asset MIME types up front — Python's default ``mimetypes`` DB
# doesn't include glTF, which would otherwise serve GLBs as ``text/plain``.
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")

from .config import get_settings
from .db import SessionLocal, init_db
from .meshy import MeshyClient
from .routes import router as generations_router
from .watcher import DEFAULT_POLL_INTERVAL_S, maybe_reconcile_in_flight

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create per-app singletons on startup and clean them up on shutdown."""
    # Ensure ``data/`` and ``data/models/`` exist and the SQLite schema is in place.
    init_db()

    # Shared Meshy client (one connection pool per process).
    app.state.meshy_client = MeshyClient(
        api_key=settings.meshy_api_key,
        api_base=settings.meshy_api_base,
    )
    # Session factory used by watchers, which run outside request scope.
    app.state.session_factory = SessionLocal
    # Strong-reference registry so fire-and-forget asyncio tasks aren't GC'd.
    app.state.background_tasks = set()
    # Poll interval and models-dir surfaced on state so tests can override them
    # without mutating the ``Settings`` singleton.
    app.state.watcher_poll_interval = DEFAULT_POLL_INTERVAL_S
    app.state.models_dir = settings.models_dir

    # Re-attach watchers for anything still in flight from a previous process.
    maybe_reconcile_in_flight(app)

    try:
        yield
    finally:
        await app.state.meshy_client.aclose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(generations_router)


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


@app.get("/files/{path:path}", include_in_schema=False)
def serve_generated_file(path: str, request: Request) -> FileResponse:
    """Serve a downloaded model or thumbnail from the local models directory.

    Reads the root from ``request.app.state.models_dir`` (populated by the
    lifespan) so tests can point it at a temp directory without touching
    production data. Path-traversal is rejected by resolving the target and
    ensuring it stays inside ``models_dir``.
    """
    root = request.app.state.models_dir
    # Resolve both sides so ``..`` segments and symlinks are normalized before
    # the containment check.
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        # ``path`` escapes ``models_dir`` — deny without leaking why.
        raise HTTPException(status_code=404, detail="file not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target)
