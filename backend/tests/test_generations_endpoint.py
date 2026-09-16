"""HTTP tests for ``POST /api/generations`` (M4).

Bypasses the FastAPI lifespan (which would create a real Meshy client) by
populating ``app.state`` manually inside a fixture; also overrides the
``get_session`` and ``get_meshy_client`` dependencies to point at the
in-memory DB and a ``FakeMeshyClient``. Runs on a single event loop via
``httpx.AsyncClient`` + ``ASGITransport`` so the fire-and-forget watcher task
can be awaited from within the test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import get_session
from app.deps import get_meshy_client
from app.main import app
from app.meshy import MeshyError, MeshyTask
from app.models import Generation, GenerationStatus

from tests.conftest import FakeMeshyClient


@pytest.fixture()
def app_with_fakes(engine: Engine, tmp_path: Path):
    """Wire the real FastAPI app to test doubles for one test.

    Returns ``(app, fake, TestingSession)`` so tests can drive requests and
    then inspect the DB and the fake's call log.
    """
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    def _override_session():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    fake = FakeMeshyClient()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_meshy_client] = lambda: fake

    # Populate what the watcher reads directly from app.state (it does not go
    # through FastAPI DI because it runs outside the request scope).
    app.state.meshy_client = fake
    app.state.session_factory = TestingSession
    app.state.background_tasks = set()
    app.state.watcher_poll_interval = 0.0
    app.state.models_dir = tmp_path

    try:
        yield app, fake, TestingSession
    finally:
        app.dependency_overrides.clear()


async def _client(app_) -> AsyncIterator[AsyncClient]:
    """Small helper to build an ASGI test client bound to the given app."""
    async with AsyncClient(
        transport=ASGITransport(app=app_), base_url="http://test"
    ) as c:
        yield c


async def _await_background_tasks(app_) -> None:
    """Await any watchers the endpoint spawned so the DB reflects final state."""
    tasks = list(app_.state.background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Happy path (immediate response) + end-to-end (watcher completes).
# ---------------------------------------------------------------------------


async def test_create_generation_returns_in_progress_and_records_task_id(
    app_with_fakes,
) -> None:
    app_, fake, _ = app_with_fakes
    # Configure the fake so the watcher stays IN_PROGRESS by the time we
    # inspect the response (it will finish shortly after and be awaited below).
    fake.task_snapshots = [
        MeshyTask(id=fake.create_task_id, status="IN_PROGRESS", progress=30),
        MeshyTask(
            id=fake.create_task_id,
            status="SUCCEEDED",
            progress=100,
            model_urls={"glb": "https://cdn/model.glb"},
            thumbnail_url="https://cdn/preview.png",
        ),
    ]

    async for c in _client(app_):
        r = await c.post("/api/generations", json={"prompt": "a monster mask"})

    assert r.status_code == 201
    body = r.json()
    assert body["prompt"] == "a monster mask"
    # Immediately after the endpoint returns, the row must be IN_PROGRESS.
    assert body["status"] == GenerationStatus.PREVIEW_IN_PROGRESS.value
    assert body["error"] is None
    # Internal Meshy task id must NOT leak in the API response.
    assert "preview_task_id" not in body
    assert fake.create_preview_calls == ["a monster mask"]

    # Clean up: let the spawned watcher finish so pytest doesn't complain.
    await _await_background_tasks(app_)


async def test_create_generation_end_to_end_watcher_downloads_and_succeeds(
    app_with_fakes,
) -> None:
    """Full flow: POST -> watcher polls and downloads -> row = SUCCEEDED, file exists."""
    app_, fake, TestingSession = app_with_fakes
    fake.task_snapshots = [
        MeshyTask(
            id=fake.create_task_id,
            status="SUCCEEDED",
            progress=100,
            model_urls={"glb": "https://cdn/model.glb"},
            thumbnail_url="https://cdn/preview.png",
        ),
    ]

    async for c in _client(app_):
        r = await c.post("/api/generations", json={"prompt": "a cube"})
    assert r.status_code == 201
    gen_id = r.json()["id"]

    await _await_background_tasks(app_)

    # DB reflects final state.
    with TestingSession() as s:
        gen = s.get(Generation, gen_id)
        assert gen is not None
        assert gen.status is GenerationStatus.PREVIEW_SUCCEEDED
        assert gen.preview_progress == 100
        assert gen.preview_model_path == f"{gen_id}/preview.glb"
        assert gen.thumbnail_path == f"{gen_id}/thumbnail.png"
        # meshy_params snapshot is stored (internal record; not on the API).
        assert gen.meshy_params.get("ai_model") == "meshy-6-lite"

    # File exists on disk under the app.state.models_dir the fixture set.
    on_disk = app_.state.models_dir / f"{gen_id}/preview.glb"
    assert on_disk.read_bytes() == fake.download_content


# ---------------------------------------------------------------------------
# Failure paths.
# ---------------------------------------------------------------------------


async def test_create_generation_persists_failure_when_meshy_rejects_creation(
    app_with_fakes,
) -> None:
    """Meshy 400 on create -> row saved as PREVIEW_FAILED, HTTP 201 still returned."""
    app_, fake, TestingSession = app_with_fakes
    fake.create_raises = MeshyError(400, {"message": "prompt too long"})

    async for c in _client(app_):
        r = await c.post("/api/generations", json={"prompt": "x"})

    assert r.status_code == 201
    body = r.json()
    assert body["status"] == GenerationStatus.PREVIEW_FAILED.value
    assert body["error"] is not None and "prompt too long" in body["error"]

    # No watcher was spawned since create failed.
    assert not app_.state.background_tasks

    # And nothing was downloaded.
    assert fake.download_calls == []


async def test_create_generation_rejects_empty_prompt(app_with_fakes) -> None:
    """Pydantic ``min_length=1`` returns 422 before any DB/Meshy work happens."""
    app_, fake, TestingSession = app_with_fakes

    async for c in _client(app_):
        r = await c.post("/api/generations", json={"prompt": ""})

    assert r.status_code == 422
    # Nothing hit Meshy or the DB.
    assert fake.create_preview_calls == []
    with TestingSession() as s:
        assert s.query(Generation).count() == 0
