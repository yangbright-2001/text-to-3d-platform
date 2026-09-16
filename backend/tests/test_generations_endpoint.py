"""HTTP tests for the generations router (M4 POST, M5 GET list/detail).

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


# ---------------------------------------------------------------------------
# M5 — Read endpoints.
# ---------------------------------------------------------------------------


async def test_list_generations_returns_newest_first(app_with_fakes) -> None:
    """List orders by ``created_at DESC`` so the newest row appears first."""
    from datetime import datetime, timezone

    app_, _, TestingSession = app_with_fakes
    older = datetime(2024, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2025, 6, 1, tzinfo=timezone.utc)
    with TestingSession() as s:
        s.add(
            Generation(
                prompt="old", status=GenerationStatus.PREVIEW_SUCCEEDED,
                created_at=older, updated_at=older,
            )
        )
        s.add(
            Generation(
                prompt="new", status=GenerationStatus.PREVIEW_SUCCEEDED,
                created_at=newer, updated_at=newer,
            )
        )
        s.commit()

    async for c in _client(app_):
        r = await c.get("/api/generations")

    assert r.status_code == 200
    body = r.json()
    assert [row["prompt"] for row in body] == ["new", "old"]


async def test_list_generations_empty_returns_empty_array(app_with_fakes) -> None:
    app_, _, _ = app_with_fakes
    async for c in _client(app_):
        r = await c.get("/api/generations")
    assert r.status_code == 200
    assert r.json() == []


async def test_get_generation_returns_row_with_files_urls(app_with_fakes) -> None:
    """Detail response converts internal ``_path`` DB columns into ``/files/`` URLs."""
    app_, _, TestingSession = app_with_fakes
    with TestingSession() as s:
        gen = Generation(
            prompt="p",
            status=GenerationStatus.PREVIEW_SUCCEEDED,
            preview_progress=100,
            preview_model_path="abc/preview.glb",
            thumbnail_path="abc/thumbnail.png",
        )
        s.add(gen)
        s.commit()
        gen_id = gen.id

    async for c in _client(app_):
        r = await c.get(f"/api/generations/{gen_id}")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == gen_id
    # URL fields prefixed with our own static mount, not raw filesystem paths.
    assert body["preview_model_url"] == "/files/abc/preview.glb"
    assert body["thumbnail_url"] == "/files/abc/thumbnail.png"
    # Internal path columns must NOT leak on the wire.
    assert "preview_model_path" not in body
    assert "thumbnail_path" not in body
    # Internal Meshy task ids must NOT leak either (regression guard from M4).
    assert "preview_task_id" not in body


async def test_get_generation_404_when_missing(app_with_fakes) -> None:
    app_, _, _ = app_with_fakes
    async for c in _client(app_):
        r = await c.get("/api/generations/does-not-exist")
    assert r.status_code == 404


async def test_generation_read_urls_are_null_when_paths_are_null(
    app_with_fakes,
) -> None:
    """A pending/in-progress row has no downloaded files yet — URLs must be null."""
    app_, _, TestingSession = app_with_fakes
    with TestingSession() as s:
        gen = Generation(prompt="p", status=GenerationStatus.PREVIEW_PENDING)
        s.add(gen)
        s.commit()
        gen_id = gen.id

    async for c in _client(app_):
        r = await c.get(f"/api/generations/{gen_id}")

    assert r.status_code == 200
    body = r.json()
    assert body["preview_model_url"] is None
    assert body["thumbnail_url"] is None
    assert body["refine_model_url"] is None
