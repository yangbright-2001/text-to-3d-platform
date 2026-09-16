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
    """List orders by ``updated_at DESC`` so a recently refined older row
    appears before a newer but untouched preview."""
    from datetime import datetime, timezone

    app_, _, TestingSession = app_with_fakes
    created_old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    created_new = datetime(2025, 6, 1, tzinfo=timezone.utc)
    refined_just_now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    with TestingSession() as s:
        s.add(
            Generation(
                prompt="old-then-refined",
                status=GenerationStatus.REFINE_SUCCEEDED,
                created_at=created_old, updated_at=refined_just_now,
            )
        )
        s.add(
            Generation(
                prompt="newer-preview",
                status=GenerationStatus.PREVIEW_SUCCEEDED,
                created_at=created_new, updated_at=created_new,
            )
        )
        s.commit()

    async for c in _client(app_):
        r = await c.get("/api/generations")

    assert r.status_code == 200
    body = r.json()
    assert [row["prompt"] for row in body] == ["old-then-refined", "newer-preview"]


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
    # Thumbnail is cache-busted so a refine that overwrites the same png
    # is not stuck behind the browser's cached preview image.
    assert body["thumbnail_url"].startswith("/files/abc/thumbnail.png?v=")
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


# ---------------------------------------------------------------------------
# M8 — Refine endpoint.
# ---------------------------------------------------------------------------


def _seed_succeeded_preview(TestingSession, prompt: str = "a cube") -> str:
    """Insert a row that's ready for refine — mirrors the state left by
    a completed preview watcher (M4)."""
    with TestingSession() as s:
        gen = Generation(
            prompt=prompt,
            status=GenerationStatus.PREVIEW_SUCCEEDED,
            preview_task_id="meshy-preview-xyz",
            preview_progress=100,
            preview_model_path="seed/preview.glb",
            thumbnail_path="seed/thumbnail.png",
            meshy_params={"mode": "preview", "ai_model": "meshy-6-lite"},
        )
        s.add(gen)
        s.commit()
        return gen.id


async def test_refine_from_succeeded_preview_starts_refine_and_downloads(
    app_with_fakes,
) -> None:
    """POST /refine transitions to REFINE_IN_PROGRESS immediately, then the
    watcher runs to REFINE_SUCCEEDED and drops the refined GLB on disk."""
    app_, fake, TestingSession = app_with_fakes
    gen_id = _seed_succeeded_preview(TestingSession)
    fake.create_task_id = "meshy-refine-xyz"
    fake.task_snapshots = [
        MeshyTask(
            id="meshy-refine-xyz",
            status="SUCCEEDED",
            progress=100,
            model_urls={"glb": "https://cdn/refine.glb"},
            thumbnail_url="https://cdn/refine-thumb.png",
        ),
    ]

    async for c in _client(app_):
        r = await c.post(f"/api/generations/{gen_id}/refine")

    assert r.status_code == 200
    body = r.json()
    # The endpoint returns the row post-Meshy-accepts (IN_PROGRESS, not PENDING).
    assert body["status"] == GenerationStatus.REFINE_IN_PROGRESS.value
    # Internal refine task id must NOT leak on the wire.
    assert "refine_task_id" not in body
    # Refine was requested against the correct preview task id.
    assert fake.create_refine_calls == ["meshy-preview-xyz"]

    await _await_background_tasks(app_)

    with TestingSession() as s:
        gen = s.get(Generation, gen_id)
        assert gen is not None
        assert gen.status is GenerationStatus.REFINE_SUCCEEDED
        assert gen.refine_progress == 100
        assert gen.refine_model_path == f"{gen_id}/refine.glb"
        # Thumbnail was overwritten with the refined version.
        assert gen.thumbnail_path == f"{gen_id}/thumbnail.png"
        # Preview path preserved so both remain individually viewable.
        assert gen.preview_model_path == "seed/preview.glb"
        # meshy_params retains the preview info AND adds the refine block.
        assert gen.meshy_params["ai_model"] == "meshy-6-lite"
        assert gen.meshy_params["refine"]["mode"] == "refine"

    # File on disk.
    on_disk = app_.state.models_dir / f"{gen_id}/refine.glb"
    assert on_disk.read_bytes() == fake.download_content


async def test_refine_not_allowed_when_status_is_not_preview_succeeded(
    app_with_fakes,
) -> None:
    """Refine is only allowed from PREVIEW_SUCCEEDED — anything else is 409."""
    app_, fake, TestingSession = app_with_fakes
    with TestingSession() as s:
        gen = Generation(
            prompt="in-flight preview",
            status=GenerationStatus.PREVIEW_IN_PROGRESS,
            preview_task_id="x",
            preview_progress=40,
        )
        s.add(gen)
        s.commit()
        gen_id = gen.id

    async for c in _client(app_):
        r = await c.post(f"/api/generations/{gen_id}/refine")

    assert r.status_code == 409
    # Detail includes the actual status so the UI can render a helpful message.
    assert "PREVIEW_IN_PROGRESS" in r.json()["detail"]
    # Nothing hit Meshy and no watcher was spawned.
    assert fake.create_refine_calls == []
    assert not app_.state.background_tasks


async def test_refine_returns_404_when_generation_missing(app_with_fakes) -> None:
    app_, fake, _ = app_with_fakes
    async for c in _client(app_):
        r = await c.post("/api/generations/does-not-exist/refine")
    assert r.status_code == 404
    assert fake.create_refine_calls == []


async def test_refine_persists_failure_when_meshy_rejects_creation(
    app_with_fakes,
) -> None:
    """Meshy 400 on refine create -> row saved as REFINE_FAILED, HTTP 200 still returned.

    The failure comes back in the response body (matching preview behavior)
    so the frontend surfaces it through the same polling channel.
    """
    app_, fake, TestingSession = app_with_fakes
    gen_id = _seed_succeeded_preview(TestingSession)
    fake.create_raises = MeshyError(400, {"message": "refine quota exceeded"})

    async for c in _client(app_):
        r = await c.post(f"/api/generations/{gen_id}/refine")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == GenerationStatus.REFINE_FAILED.value
    assert "refine quota exceeded" in body["error"]
    # No watcher spawned — nothing to poll.
    assert not app_.state.background_tasks
    # Preview URLs still present on the response (refine failure preserves them).
    assert body["preview_model_url"] == "/files/seed/preview.glb"

    # DB reflects it too.
    with TestingSession() as s:
        gen = s.get(Generation, gen_id)
        assert gen is not None
        assert gen.status is GenerationStatus.REFINE_FAILED
        assert gen.preview_model_path == "seed/preview.glb"  # preview preserved
        assert gen.refine_model_path is None
