"""HTTP routes for generations.

- M4 shipped ``POST /api/generations``.
- M5 added list + detail read endpoints and started returning ``/files/...``
  URLs (not raw paths) via ``GenerationRead.from_generation``.
- M8 adds ``POST /api/generations/{id}/refine`` — user-initiated refine that
  reuses the preview watcher pattern with the refine-side task id.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .deps import get_meshy_client
from .meshy import MeshyClient, MeshyError
from .models import Generation, GenerationStatus
from .schemas import GenerationCreate, GenerationRead
from .watcher import (
    PREVIEW_MESHY_PARAMS,
    REFINE_MESHY_PARAMS,
    watch_preview,
    watch_refine,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/generations", tags=["generations"])


@router.post(
    "",
    response_model=GenerationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_generation(
    payload: GenerationCreate,
    request: Request,
    session: Session = Depends(get_session),
    meshy: MeshyClient = Depends(get_meshy_client),
) -> GenerationRead:
    """Submit a prompt and start a preview generation.

    Returns immediately with the current app-level row. If Meshy rejects the
    task synchronously (e.g., moderation), the row is persisted as
    ``PREVIEW_FAILED`` and returned — the request itself still succeeds so the
    failure shows up in the Task Tracker.
    """
    # 1. Persist a PREVIEW_PENDING row so the generation is durable even if
    # the process dies before Meshy responds.
    gen = Generation(
        prompt=payload.prompt.strip(),
        status=GenerationStatus.PREVIEW_PENDING,
    )
    session.add(gen)
    session.commit()
    session.refresh(gen)

    # 2. Ask Meshy to create the preview task. Any error is recorded on the
    # row rather than raised as HTTP 5xx — see docstring rationale.
    try:
        meshy_task_id = await meshy.create_preview_task(gen.prompt)
    except MeshyError as exc:
        log.warning("preview create failed for %s: %s", gen.id, exc)
        gen.status = GenerationStatus.PREVIEW_FAILED
        gen.error = f"Failed to create Meshy task: {exc}"
        session.commit()
        session.refresh(gen)
        return GenerationRead.from_generation(gen)

    # 3. Advance to PREVIEW_IN_PROGRESS and remember the parameters we sent so
    # historical rows stay self-describing if defaults change later.
    gen.preview_task_id = meshy_task_id
    gen.meshy_params = dict(PREVIEW_MESHY_PARAMS)
    gen.status = GenerationStatus.PREVIEW_IN_PROGRESS
    session.commit()
    session.refresh(gen)

    # 4. Fire and forget the polling watcher on the running event loop.
    _spawn_preview_watcher(request, gen.id)

    return GenerationRead.from_generation(gen)


@router.get("", response_model=list[GenerationRead])
def list_generations(session: Session = Depends(get_session)) -> list[GenerationRead]:
    """Return all generations, newest first — the Task Tracker's data source."""
    # Secondary sort by id keeps ordering stable when two rows share a
    # timestamp (possible in fast tests running under one millisecond).
    rows = session.execute(
        select(Generation).order_by(
            Generation.created_at.desc(), Generation.id.desc()
        )
    ).scalars().all()
    return [GenerationRead.from_generation(g) for g in rows]


@router.get("/{gen_id}", response_model=GenerationRead)
def get_generation(
    gen_id: str, session: Session = Depends(get_session)
) -> GenerationRead:
    """Return a single generation. This is the frontend's polling target."""
    gen = session.get(Generation, gen_id)
    if gen is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return GenerationRead.from_generation(gen)


@router.post(
    "/{gen_id}/refine",
    response_model=GenerationRead,
)
async def refine_generation(
    gen_id: str,
    request: Request,
    session: Session = Depends(get_session),
    meshy: MeshyClient = Depends(get_meshy_client),
) -> GenerationRead:
    """Explicitly start a refine on a succeeded preview.

    Rules (per PLAN.md):
      * Refine is user-initiated — this endpoint is the only entry point.
      * Only allowed from ``PREVIEW_SUCCEEDED``; anything else is 409 so the
        frontend can render a clear message.
      * A failed refine does not invalidate the underlying preview.
    """
    gen = session.get(Generation, gen_id)
    if gen is None:
        raise HTTPException(status_code=404, detail="generation not found")

    if gen.status != GenerationStatus.PREVIEW_SUCCEEDED:
        # Includes the current status so the frontend can distinguish
        # "still previewing", "already refining", and "already refined".
        raise HTTPException(
            status_code=409,
            detail=f"cannot refine: current status is {gen.status.value}",
        )

    # Defensive: the state machine guarantees a PREVIEW_SUCCEEDED row has a
    # preview_task_id (M4 sets it before flipping status). Guard anyway to
    # produce a legible error rather than a downstream Meshy 400.
    if not gen.preview_task_id:
        raise HTTPException(
            status_code=500,
            detail="generation has no preview task id",
        )

    # 1. Commit REFINE_PENDING before hitting Meshy, mirroring the preview
    # endpoint's PENDING-first pattern. If the process dies between this
    # commit and the Meshy call, M10 startup reconciliation can pick the row
    # up from a well-defined "we intended to refine" state.
    gen.status = GenerationStatus.REFINE_PENDING
    gen.refine_progress = 0
    # Clear any stale error field so REFINE_FAILED below is unambiguous.
    gen.error = None
    session.commit()
    session.refresh(gen)

    # 2. Ask Meshy to create the refine task. Any error is recorded on the
    # row (REFINE_FAILED) and returned — HTTP itself still succeeds so the
    # frontend can surface the failure without a separate error channel.
    try:
        refine_task_id = await meshy.create_refine_task(gen.preview_task_id)
    except MeshyError as exc:
        log.warning("refine create failed for %s: %s", gen.id, exc)
        gen.status = GenerationStatus.REFINE_FAILED
        gen.error = f"Failed to create Meshy refine task: {exc}"
        session.commit()
        session.refresh(gen)
        return GenerationRead.from_generation(gen)

    # 3. Advance to REFINE_IN_PROGRESS and record the refine params
    # alongside the preview params already stored on this row.
    gen.refine_task_id = refine_task_id
    # Additive merge: preserves the flat preview shape M4 wrote so existing
    # rows (and any downstream consumers) stay backward-compatible.
    gen.meshy_params = {
        **(gen.meshy_params or {}),
        "refine": dict(REFINE_MESHY_PARAMS),
    }
    gen.status = GenerationStatus.REFINE_IN_PROGRESS
    session.commit()
    session.refresh(gen)

    # 4. Fire and forget the refine watcher.
    _spawn_refine_watcher(request, gen.id)

    return GenerationRead.from_generation(gen)


def _spawn_preview_watcher(request: Request, gen_id: str) -> None:
    """Schedule a preview watcher on the app's event loop.

    Keeps a strong reference in ``app.state.background_tasks`` so the task is
    not GC'd while running — this is the recommended pattern for
    ``asyncio.create_task`` fire-and-forget usage.
    """
    app = request.app
    task = asyncio.create_task(
        watch_preview(
            gen_id=gen_id,
            meshy=app.state.meshy_client,
            session_factory=app.state.session_factory,
            models_dir=app.state.models_dir,
            poll_interval=app.state.watcher_poll_interval,
        )
    )
    app.state.background_tasks.add(task)
    task.add_done_callback(app.state.background_tasks.discard)


def _spawn_refine_watcher(request: Request, gen_id: str) -> None:
    """Structural twin of ``_spawn_preview_watcher`` for the refine stage."""
    app = request.app
    task = asyncio.create_task(
        watch_refine(
            gen_id=gen_id,
            meshy=app.state.meshy_client,
            session_factory=app.state.session_factory,
            models_dir=app.state.models_dir,
            poll_interval=app.state.watcher_poll_interval,
        )
    )
    app.state.background_tasks.add(task)
    task.add_done_callback(app.state.background_tasks.discard)
