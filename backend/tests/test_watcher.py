"""Unit tests for the preview watcher (M4).

Uses a real in-memory SQLite (via the shared ``engine``/``session_factory``
fixtures) and a ``FakeMeshyClient`` so full state-machine transitions and
disk-side effects are exercised end to end without any network calls.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.meshy import MeshyError, MeshyTask
from app.models import Generation, GenerationStatus
from app.watcher import watch_preview, watch_refine

from tests.conftest import FakeMeshyClient


# ---------------------------------------------------------------------------
# Small helpers to keep tests focused on assertions rather than setup.
# ---------------------------------------------------------------------------


def _seed_generation(
    session_factory: sessionmaker, *, task_id: str = "meshy-task-abc"
) -> str:
    """Create a Generation already in PREVIEW_PENDING with the task id set."""
    with session_factory() as s:
        gen = Generation(
            prompt="a cube",
            status=GenerationStatus.PREVIEW_PENDING,
            preview_task_id=task_id,
        )
        s.add(gen)
        s.commit()
        s.refresh(gen)
        return gen.id


def _get(session_factory: sessionmaker, gen_id: str) -> Generation:
    with session_factory() as s:
        gen = s.get(Generation, gen_id)
        assert gen is not None
        return gen


# ---------------------------------------------------------------------------
# Full success path.
# ---------------------------------------------------------------------------


async def test_watcher_full_success_downloads_and_marks_succeeded(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    gen_id = _seed_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(id="meshy-task-abc", status="IN_PROGRESS", progress=50),
            MeshyTask(
                id="meshy-task-abc",
                status="SUCCEEDED",
                progress=100,
                model_urls={"glb": "https://cdn.example/model.glb?Expires=1"},
                thumbnail_url="https://cdn.example/preview.png?Expires=1",
            ),
        ],
    )

    await watch_preview(
        gen_id=gen_id,
        meshy=fake,
        session_factory=session_factory,
        models_dir=tmp_path,
        poll_interval=0.0,  # drive the loop instantly
    )

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.PREVIEW_SUCCEEDED
    assert gen.preview_progress == 100
    # Paths are relative and follow ``<gen_id>/<file>`` layout.
    assert gen.preview_model_path == f"{gen_id}/preview.glb"
    assert gen.thumbnail_path == f"{gen_id}/thumbnail.png"

    # Files really exist on disk with the fake content.
    assert (tmp_path / gen.preview_model_path).read_bytes() == fake.download_content
    assert (tmp_path / gen.thumbnail_path).read_bytes() == fake.download_content
    # Both URLs were downloaded (order: GLB first, then thumbnail).
    assert [u for u, _ in fake.download_calls] == [
        "https://cdn.example/model.glb?Expires=1",
        "https://cdn.example/preview.png?Expires=1",
    ]


# ---------------------------------------------------------------------------
# Failure paths.
# ---------------------------------------------------------------------------


async def test_watcher_meshy_failed_marks_failed_with_message(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    gen_id = _seed_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(
                id="meshy-task-abc",
                status="FAILED",
                progress=0,
                error_message="content moderation blocked",
            ),
        ],
    )

    await watch_preview(gen_id, fake, session_factory, tmp_path, poll_interval=0.0)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.PREVIEW_FAILED
    assert gen.error == "content moderation blocked"
    # No download attempted on failure.
    assert fake.download_calls == []


async def test_watcher_succeeded_without_glb_url_marks_failed(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """Success without a GLB URL is unusable — treat as a failure."""
    gen_id = _seed_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(id="meshy-task-abc", status="SUCCEEDED", progress=100, model_urls={}),
        ],
    )

    await watch_preview(gen_id, fake, session_factory, tmp_path, poll_interval=0.0)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.PREVIEW_FAILED
    assert gen.error is not None and "no GLB URL" in gen.error
    assert fake.download_calls == []


async def test_watcher_get_task_error_marks_failed(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """A MeshyError while polling terminates the watcher with an error record."""
    gen_id = _seed_generation(session_factory)
    fake = FakeMeshyClient(
        # Snapshots ignored — get_task raises on the first call.
        task_snapshots=[MeshyTask(id="x", status="IN_PROGRESS", progress=0)],
        get_raises_on_call=1,
    )

    await watch_preview(gen_id, fake, session_factory, tmp_path, poll_interval=0.0)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.PREVIEW_FAILED
    assert gen.error is not None and "Meshy error" in gen.error


# ---------------------------------------------------------------------------
# State machine detail.
# ---------------------------------------------------------------------------


async def test_watcher_advances_pending_to_in_progress_on_first_snapshot(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """The row starts at PREVIEW_PENDING; the first IN_PROGRESS snapshot flips it."""
    gen_id = _seed_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(id="meshy-task-abc", status="IN_PROGRESS", progress=10),
            MeshyTask(
                id="meshy-task-abc",
                status="SUCCEEDED",
                progress=100,
                model_urls={"glb": "https://cdn.example/model.glb"},
            ),
        ],
    )

    await watch_preview(gen_id, fake, session_factory, tmp_path, poll_interval=0.0)

    gen = _get(session_factory, gen_id)
    # After the full run we should have ended at SUCCEEDED, which is only
    # reachable by having gone through IN_PROGRESS (state machine invariant).
    assert gen.status is GenerationStatus.PREVIEW_SUCCEEDED


# ---------------------------------------------------------------------------
# Refine watcher tests (M8). The refine stage assumes a row already reached
# PREVIEW_SUCCEEDED and the refine endpoint has committed a REFINE_IN_PROGRESS
# row with a ``refine_task_id`` — the tests seed that state directly to keep
# each test focused on the watcher.
# ---------------------------------------------------------------------------


def _seed_refining_generation(
    session_factory: sessionmaker,
    *,
    refine_task_id: str = "meshy-refine-abc",
) -> str:
    """Create a Generation already at REFINE_IN_PROGRESS with a preview model.

    Mirrors what ``POST /api/generations/{id}/refine`` would leave in the DB
    just before spawning the watcher — including a downloaded preview GLB
    path so we can assert that a failed refine preserves it.
    """
    with session_factory() as s:
        gen = Generation(
            prompt="a cube",
            status=GenerationStatus.REFINE_IN_PROGRESS,
            preview_task_id="meshy-preview-abc",
            preview_progress=100,
            preview_model_path="dummy/preview.glb",
            thumbnail_path="dummy/thumbnail.png",
            refine_task_id=refine_task_id,
            refine_progress=0,
        )
        s.add(gen)
        s.commit()
        s.refresh(gen)
        return gen.id


async def test_refine_watcher_full_success_downloads_and_marks_succeeded(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    gen_id = _seed_refining_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(id="meshy-refine-abc", status="IN_PROGRESS", progress=60),
            MeshyTask(
                id="meshy-refine-abc",
                status="SUCCEEDED",
                progress=100,
                model_urls={"glb": "https://cdn.example/refine.glb?Expires=1"},
                thumbnail_url="https://cdn.example/refine-thumb.png?Expires=1",
            ),
        ],
    )

    await watch_refine(
        gen_id=gen_id,
        meshy=fake,
        session_factory=session_factory,
        models_dir=tmp_path,
        poll_interval=0.0,
    )

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.REFINE_SUCCEEDED
    assert gen.refine_progress == 100
    assert gen.refine_model_path == f"{gen_id}/refine.glb"
    # Fresh thumbnail overwrites the preview one (textured version is more
    # useful for the tracker page).
    assert gen.thumbnail_path == f"{gen_id}/thumbnail.png"
    # Preview path is preserved so both models remain individually viewable.
    assert gen.preview_model_path == "dummy/preview.glb"

    assert (tmp_path / gen.refine_model_path).read_bytes() == fake.download_content
    assert [u for u, _ in fake.download_calls] == [
        "https://cdn.example/refine.glb?Expires=1",
        "https://cdn.example/refine-thumb.png?Expires=1",
    ]


async def test_refine_watcher_meshy_failed_marks_refine_failed_only(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    """A refine failure marks the row REFINE_FAILED but preserves the preview."""
    gen_id = _seed_refining_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(
                id="meshy-refine-abc",
                status="FAILED",
                progress=0,
                error_message="refine backend unavailable",
            ),
        ],
    )

    await watch_refine(gen_id, fake, session_factory, tmp_path, poll_interval=0.0)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.REFINE_FAILED
    assert gen.error == "refine backend unavailable"
    # PLAN.md: "A failed refine does not invalidate the viewable preview."
    assert gen.preview_model_path == "dummy/preview.glb"
    assert gen.thumbnail_path == "dummy/thumbnail.png"
    assert gen.refine_model_path is None
    assert fake.download_calls == []


async def test_refine_watcher_succeeded_without_glb_url_marks_failed(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    gen_id = _seed_refining_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[
            MeshyTask(id="meshy-refine-abc", status="SUCCEEDED", progress=100, model_urls={}),
        ],
    )

    await watch_refine(gen_id, fake, session_factory, tmp_path, poll_interval=0.0)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.REFINE_FAILED
    assert gen.error is not None and "no GLB URL" in gen.error
    # Preview is still viewable.
    assert gen.preview_model_path == "dummy/preview.glb"
    assert fake.download_calls == []


async def test_refine_watcher_get_task_error_marks_refine_failed(
    session_factory: sessionmaker, tmp_path: Path
) -> None:
    gen_id = _seed_refining_generation(session_factory)
    fake = FakeMeshyClient(
        task_snapshots=[MeshyTask(id="x", status="IN_PROGRESS", progress=0)],
        get_raises_on_call=1,
    )

    await watch_refine(gen_id, fake, session_factory, tmp_path, poll_interval=0.0)

    gen = _get(session_factory, gen_id)
    assert gen.status is GenerationStatus.REFINE_FAILED
    assert gen.error is not None and "Meshy error" in gen.error
    assert gen.preview_model_path == "dummy/preview.glb"
