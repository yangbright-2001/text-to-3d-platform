"""Startup reconciliation (M10): respawn watchers for in-flight DB rows.

Calls ``reconcile_in_flight`` directly against a fake ``app.state`` so we
never go through FastAPI's lifespan (which tests skip via
``TEXT3D_SKIP_RECONCILE=1``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from app.meshy import MeshyTask
from app.models import Generation, GenerationStatus
from app.watcher import reconcile_in_flight

from tests.conftest import FakeMeshyClient


def _app(session_factory: sessionmaker, fake: FakeMeshyClient, tmp_path: Path):
    """Minimal FastAPI-app double: reconcile only reads ``app.state``."""
    return SimpleNamespace(
        state=SimpleNamespace(
            meshy_client=fake,
            session_factory=session_factory,
            models_dir=tmp_path,
            watcher_poll_interval=0.0,
            background_tasks=set(),
        )
    )


async def _await_spawned(app) -> None:
    tasks = list(app.state.background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _get(session_factory: sessionmaker, gen_id: str) -> Generation:
    with session_factory() as s:
        gen = s.get(Generation, gen_id)
        assert gen is not None
        return gen


async def test_reconcile_respawns_preview_in_progress(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """A crashed PREVIEW_IN_PROGRESS watcher is restarted and finishes."""
    with session_factory() as s:
        gen = Generation(
            prompt="a cube",
            status=GenerationStatus.PREVIEW_IN_PROGRESS,
            preview_task_id="meshy-preview",
            preview_progress=40,
        )
        s.add(gen)
        s.commit()
        gen_id = gen.id

    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(
                id="meshy-preview",
                status="SUCCEEDED",
                progress=100,
                model_urls={"glb": "https://cdn/model.glb"},
                thumbnail_url="https://cdn/thumb.png",
            )
        ]
    )
    app = _app(session_factory, fake, tmp_path)
    reconcile_in_flight(app)
    assert len(app.state.background_tasks) == 1
    await _await_spawned(app)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.PREVIEW_SUCCEEDED
    assert gen.preview_model_path == f"{gen_id}/preview.glb"
    assert (tmp_path / gen.preview_model_path).is_file()


async def test_reconcile_respawns_refine_in_progress(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """A crashed REFINE_IN_PROGRESS watcher is restarted; preview is kept."""
    with session_factory() as s:
        gen = Generation(
            prompt="a cube",
            status=GenerationStatus.REFINE_IN_PROGRESS,
            preview_task_id="meshy-preview",
            preview_progress=100,
            preview_model_path="seed/preview.glb",
            refine_task_id="meshy-refine",
            refine_progress=10,
        )
        s.add(gen)
        s.commit()
        gen_id = gen.id

    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(
                id="meshy-refine",
                status="SUCCEEDED",
                progress=100,
                model_urls={"glb": "https://cdn/refine.glb"},
            )
        ]
    )
    app = _app(session_factory, fake, tmp_path)
    reconcile_in_flight(app)
    await _await_spawned(app)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.REFINE_SUCCEEDED
    assert gen.refine_model_path == f"{gen_id}/refine.glb"
    assert gen.preview_model_path == "seed/preview.glb"


async def test_reconcile_fails_preview_pending_without_task_id(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """Died after PENDING commit, before Meshy accepted — do not retry create."""
    with session_factory() as s:
        gen = Generation(prompt="a cube", status=GenerationStatus.PREVIEW_PENDING)
        s.add(gen)
        s.commit()
        gen_id = gen.id

    fake = FakeMeshyClient()
    app = _app(session_factory, fake, tmp_path)
    reconcile_in_flight(app)

    assert app.state.background_tasks == set()
    assert fake.create_preview_calls == []
    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.PREVIEW_FAILED
    assert gen.error is not None and "Interrupted" in gen.error


async def test_reconcile_fails_refine_pending_without_task_id_keeps_preview(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """Same crash window on refine: fail refine, keep the viewable preview."""
    with session_factory() as s:
        gen = Generation(
            prompt="a cube",
            status=GenerationStatus.REFINE_PENDING,
            preview_task_id="meshy-preview",
            preview_progress=100,
            preview_model_path="seed/preview.glb",
        )
        s.add(gen)
        s.commit()
        gen_id = gen.id

    fake = FakeMeshyClient()
    app = _app(session_factory, fake, tmp_path)
    reconcile_in_flight(app)

    assert fake.create_refine_calls == []
    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.REFINE_FAILED
    assert gen.preview_model_path == "seed/preview.glb"
    assert gen.error is not None and "Interrupted" in gen.error


async def test_reconcile_ignores_terminal_rows(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    with session_factory() as s:
        s.add(
            Generation(
                prompt="done",
                status=GenerationStatus.PREVIEW_SUCCEEDED,
                preview_task_id="x",
                preview_progress=100,
            )
        )
        s.add(
            Generation(
                prompt="failed",
                status=GenerationStatus.PREVIEW_FAILED,
                error="nope",
            )
        )
        s.commit()

    fake = FakeMeshyClient()
    app = _app(session_factory, fake, tmp_path)
    reconcile_in_flight(app)
    assert app.state.background_tasks == set()
    assert fake.download_calls == []
