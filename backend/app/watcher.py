"""Background watchers that poll Meshy and persist generation progress.

Runs as an in-process ``asyncio`` task spawned by the endpoint handler. No
message queue, no external worker: SQLite is the source of truth so a restart
can respawn watchers for any non-terminal row (M10 startup reconciliation).

Design choices (see PLAN.md):
- Each DB write happens inside a short ``sessionmaker`` transaction, not a
  long-lived request-scoped session — the watcher outlives requests and must
  keep SQLite locks brief.
- The Meshy client is passed in explicitly rather than imported, so tests
  inject a ``FakeMeshyClient`` without patching module globals.
- Preview (M4) and refine (M8) share the exact same shape: load a task id,
  poll it to a terminal state, download assets on success. They live as two
  named entry points (``watch_preview`` / ``watch_refine``) for clear log
  messages and to leave room for stage-specific divergence later. The shared
  failure helpers take an explicit ``target`` status so the state machine is
  never touched by "guess which stage we're in" logic.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .meshy import (
    DEFAULT_PREVIEW_AI_MODEL,
    DEFAULT_REFINE_ENABLE_PBR,
    DEFAULT_REFINE_TEXTURE_RESOLUTION,
    DEFAULT_TARGET_FORMATS,
    MeshyClient,
    MeshyError,
    MeshyTask,
)
from .models import Generation, GenerationStatus, can_transition

# Default watcher poll interval used in production. Overridden per-app via
# ``app.state.watcher_poll_interval`` so tests can drive the loop instantly.
DEFAULT_POLL_INTERVAL_S = 5.0

# Constants used to advertise the parameters we sent to Meshy — persisted on
# ``Generation.meshy_params`` so historical rows remain self-describing even
# if defaults change later. Refine params are stored under the ``"refine"``
# key so the flat preview shape written by M4 stays backward-compatible.
PREVIEW_MESHY_PARAMS: dict[str, object] = {
    "mode": "preview",
    "ai_model": DEFAULT_PREVIEW_AI_MODEL,
    "target_formats": list(DEFAULT_TARGET_FORMATS),
}

REFINE_MESHY_PARAMS: dict[str, object] = {
    "mode": "refine",
    "enable_pbr": DEFAULT_REFINE_ENABLE_PBR,
    "texture_resolution": DEFAULT_REFINE_TEXTURE_RESOLUTION,
    "target_formats": list(DEFAULT_TARGET_FORMATS),
}

log = logging.getLogger(__name__)

# Type alias for the sessionmaker-style callable the watcher accepts. Written
# without importing ``sessionmaker`` explicitly to keep signatures readable.
SessionFactory = Callable[[], Session]


# ---------------------------------------------------------------------------
# Preview watcher (M4).
# ---------------------------------------------------------------------------


async def watch_preview(
    gen_id: str,
    meshy: MeshyClient,
    session_factory: SessionFactory,
    models_dir: Path,
    poll_interval: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Poll Meshy for one preview task until it terminates, then finalize.

    ``gen_id`` is our application-level id; the Meshy task id is read from
    the DB row so a restarted watcher (M10) does not need it passed in.
    """

    task_id = _load_preview_task_id(session_factory, gen_id)
    if task_id is None:
        # Row deleted or preview_task_id not yet populated — nothing to do.
        return

    while True:
        try:
            snapshot = await meshy.get_task(task_id)
        except MeshyError as exc:
            # Simple M4 policy: any Meshy error mid-poll is terminal. A future
            # milestone can add bounded retries here if transient 5xx happen.
            log.warning("preview watcher: Meshy error for %s: %s", gen_id, exc)
            _finalize_failure(
                session_factory,
                gen_id,
                f"Meshy error: {exc}",
                target=GenerationStatus.PREVIEW_FAILED,
            )
            return

        finished = _apply_preview_snapshot(session_factory, gen_id, snapshot)
        if finished:
            if snapshot.status == "SUCCEEDED":
                await _download_preview_assets(
                    gen_id, snapshot, meshy, session_factory, models_dir
                )
            return

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Refine watcher (M8). Structural twin of ``watch_preview``.
# ---------------------------------------------------------------------------


async def watch_refine(
    gen_id: str,
    meshy: MeshyClient,
    session_factory: SessionFactory,
    models_dir: Path,
    poll_interval: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Poll Meshy for one refine task until it terminates, then finalize.

    Failure policy differs slightly from preview: a failed refine does NOT
    invalidate the viewable preview (see PLAN.md), so the row keeps its
    ``preview_model_path`` intact — we only clear/replace the refine-specific
    fields.
    """

    task_id = _load_refine_task_id(session_factory, gen_id)
    if task_id is None:
        return

    while True:
        try:
            snapshot = await meshy.get_task(task_id)
        except MeshyError as exc:
            log.warning("refine watcher: Meshy error for %s: %s", gen_id, exc)
            _finalize_failure(
                session_factory,
                gen_id,
                f"Meshy error: {exc}",
                target=GenerationStatus.REFINE_FAILED,
            )
            return

        finished = _apply_refine_snapshot(session_factory, gen_id, snapshot)
        if finished:
            if snapshot.status == "SUCCEEDED":
                await _download_refine_assets(
                    gen_id, snapshot, meshy, session_factory, models_dir
                )
            return

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# DB helpers — each opens its own short session so the watcher never holds a
# SQLite write lock while waiting on the network.
# ---------------------------------------------------------------------------


def _load_preview_task_id(session_factory: SessionFactory, gen_id: str) -> str | None:
    """Read the Meshy preview task id previously written by the endpoint."""
    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return None
        return gen.preview_task_id


def _load_refine_task_id(session_factory: SessionFactory, gen_id: str) -> str | None:
    """Read the Meshy refine task id previously written by the refine endpoint."""
    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return None
        return gen.refine_task_id


def _apply_preview_snapshot(
    session_factory: SessionFactory, gen_id: str, snapshot: MeshyTask
) -> bool:
    """Persist one Meshy preview snapshot to the row. Returns True if terminal."""
    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return True  # Row deleted mid-flight — bail out.

        gen.preview_progress = snapshot.progress

        if snapshot.status in ("PENDING", "IN_PROGRESS"):
            # First non-zero progress advances the app-level state machine.
            if gen.status == GenerationStatus.PREVIEW_PENDING and can_transition(
                gen.status, GenerationStatus.PREVIEW_IN_PROGRESS
            ):
                gen.status = GenerationStatus.PREVIEW_IN_PROGRESS
            session.commit()
            return False

        if snapshot.status == "SUCCEEDED":
            # Edge case: Meshy jumps from PENDING straight to SUCCEEDED — walk
            # through IN_PROGRESS to keep the state machine linear.
            if gen.status == GenerationStatus.PREVIEW_PENDING:
                gen.status = GenerationStatus.PREVIEW_IN_PROGRESS
            session.commit()
            return True

        # FAILED / CANCELED — record error and stop polling.
        message = snapshot.error_message or f"Meshy status: {snapshot.status}"
        _apply_failure(gen, message, target=GenerationStatus.PREVIEW_FAILED)
        session.commit()
        return True


def _apply_refine_snapshot(
    session_factory: SessionFactory, gen_id: str, snapshot: MeshyTask
) -> bool:
    """Persist one Meshy refine snapshot to the row. Returns True if terminal.

    Mirrors ``_apply_preview_snapshot`` but reads/writes the refine-side
    fields and transitions along the ``REFINE_*`` state machine branch.
    """
    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return True

        gen.refine_progress = snapshot.progress

        if snapshot.status in ("PENDING", "IN_PROGRESS"):
            # Endpoint jumps straight to REFINE_IN_PROGRESS, but this guard
            # covers the M10 reconciliation path where a crashed watcher may
            # have left a row at REFINE_PENDING.
            if gen.status == GenerationStatus.REFINE_PENDING and can_transition(
                gen.status, GenerationStatus.REFINE_IN_PROGRESS
            ):
                gen.status = GenerationStatus.REFINE_IN_PROGRESS
            session.commit()
            return False

        if snapshot.status == "SUCCEEDED":
            if gen.status == GenerationStatus.REFINE_PENDING:
                gen.status = GenerationStatus.REFINE_IN_PROGRESS
            session.commit()
            return True

        message = snapshot.error_message or f"Meshy status: {snapshot.status}"
        _apply_failure(gen, message, target=GenerationStatus.REFINE_FAILED)
        session.commit()
        return True


def _apply_failure(
    gen: Generation, message: str, *, target: GenerationStatus
) -> None:
    """Move a row to ``target`` (if the state machine allows) and record ``error``.

    The ``target`` is always ``PREVIEW_FAILED`` or ``REFINE_FAILED``. Callers
    pass it explicitly so we never have to infer which stage we're in from
    the row's current status (which would be fragile in the M10 reconciliation
    path where a watcher might restart from any non-terminal state).
    """
    if can_transition(gen.status, target):
        gen.status = target
    gen.error = message


def _finalize_failure(
    session_factory: SessionFactory,
    gen_id: str,
    message: str,
    *,
    target: GenerationStatus,
) -> None:
    """Standalone helper used when failure is discovered outside the snapshot flow."""
    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return
        _apply_failure(gen, message, target=target)
        session.commit()


# ---------------------------------------------------------------------------
# Asset download — happens on SUCCEEDED. GLB is required; thumbnail is best-effort.
# ---------------------------------------------------------------------------


async def _download_preview_assets(
    gen_id: str,
    snapshot: MeshyTask,
    meshy: MeshyClient,
    session_factory: SessionFactory,
    models_dir: Path,
) -> None:
    """Fetch the preview GLB (and thumbnail, if present) and update the row.

    Failure policy:
      * missing / failed GLB download → PREVIEW_FAILED (asset is required for the viewer)
      * failed thumbnail download → keep going; the preview is still viewable
    """
    glb_url = snapshot.model_urls.get("glb")
    if not glb_url:
        _finalize_failure(
            session_factory,
            gen_id,
            "Meshy SUCCEEDED but returned no GLB URL",
            target=GenerationStatus.PREVIEW_FAILED,
        )
        return

    # Files live under ``<models_dir>/<gen_id>/`` so all assets for one
    # generation are colocated and easy to serve/list/delete later.
    glb_rel = f"{gen_id}/preview.glb"
    try:
        await meshy.download_to(glb_url, models_dir / glb_rel)
    except MeshyError as exc:
        _finalize_failure(
            session_factory,
            gen_id,
            f"GLB download failed: {exc}",
            target=GenerationStatus.PREVIEW_FAILED,
        )
        return

    thumbnail_rel: str | None = None
    if snapshot.thumbnail_url:
        thumbnail_rel = f"{gen_id}/thumbnail.png"
        try:
            await meshy.download_to(snapshot.thumbnail_url, models_dir / thumbnail_rel)
        except MeshyError as exc:
            # Thumbnail is optional for viewing — log and continue.
            log.info("thumbnail download failed for %s: %s", gen_id, exc)
            thumbnail_rel = None

    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return
        gen.preview_model_path = glb_rel
        if thumbnail_rel:
            gen.thumbnail_path = thumbnail_rel
        # Meshy sometimes reports 99 progress on SUCCEEDED; force 100 for the UI.
        gen.preview_progress = 100
        if can_transition(gen.status, GenerationStatus.PREVIEW_SUCCEEDED):
            gen.status = GenerationStatus.PREVIEW_SUCCEEDED
        session.commit()


async def _download_refine_assets(
    gen_id: str,
    snapshot: MeshyTask,
    meshy: MeshyClient,
    session_factory: SessionFactory,
    models_dir: Path,
) -> None:
    """Fetch the refined GLB and update the row.

    Failure policy differs from preview: a missing GLB / failed download
    marks the row REFINE_FAILED, but the existing ``preview_model_path`` and
    ``preview_progress`` are left untouched so the frontend can keep showing
    the untextured preview (PLAN.md: "A failed refine does not invalidate
    the viewable preview").

    Thumbnail handling: if Meshy returns a fresh thumbnail (typically shows
    the textured model), we overwrite the preview thumbnail so M9's tracker
    displays the refined version by default. This is intentional — one row
    has one canonical thumbnail slot; the fresher one is more useful.
    """
    glb_url = snapshot.model_urls.get("glb")
    if not glb_url:
        _finalize_failure(
            session_factory,
            gen_id,
            "Meshy refine SUCCEEDED but returned no GLB URL",
            target=GenerationStatus.REFINE_FAILED,
        )
        return

    glb_rel = f"{gen_id}/refine.glb"
    try:
        await meshy.download_to(glb_url, models_dir / glb_rel)
    except MeshyError as exc:
        _finalize_failure(
            session_factory,
            gen_id,
            f"Refine GLB download failed: {exc}",
            target=GenerationStatus.REFINE_FAILED,
        )
        return

    thumbnail_rel: str | None = None
    if snapshot.thumbnail_url:
        thumbnail_rel = f"{gen_id}/thumbnail.png"
        try:
            await meshy.download_to(snapshot.thumbnail_url, models_dir / thumbnail_rel)
        except MeshyError as exc:
            log.info("refine thumbnail download failed for %s: %s", gen_id, exc)
            thumbnail_rel = None

    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return
        gen.refine_model_path = glb_rel
        if thumbnail_rel:
            # Overwrite deliberately — see docstring rationale.
            gen.thumbnail_path = thumbnail_rel
        gen.refine_progress = 100
        if can_transition(gen.status, GenerationStatus.REFINE_SUCCEEDED):
            gen.status = GenerationStatus.REFINE_SUCCEEDED
        session.commit()


# ---------------------------------------------------------------------------
# Spawn helpers + startup reconciliation (M10).
# ---------------------------------------------------------------------------

# Statuses whose watcher may have died with the process. Terminal rows are
# left alone — there is nothing to poll.
_IN_FLIGHT: frozenset[GenerationStatus] = frozenset(
    {
        GenerationStatus.PREVIEW_PENDING,
        GenerationStatus.PREVIEW_IN_PROGRESS,
        GenerationStatus.REFINE_PENDING,
        GenerationStatus.REFINE_IN_PROGRESS,
    }
)

_PREVIEW_IN_FLIGHT: frozenset[GenerationStatus] = frozenset(
    {GenerationStatus.PREVIEW_PENDING, GenerationStatus.PREVIEW_IN_PROGRESS}
)
_REFINE_IN_FLIGHT: frozenset[GenerationStatus] = frozenset(
    {GenerationStatus.REFINE_PENDING, GenerationStatus.REFINE_IN_PROGRESS}
)

# Tests set this so TestClient(lifespan) never scans the developer's
# production ``data/app.db`` or calls Meshy. Real uvicorn runs do reconcile.
SKIP_RECONCILE_ENV = "TEXT3D_SKIP_RECONCILE"


def spawn_preview_watcher(app: Any, gen_id: str) -> None:
    """Fire-and-forget ``watch_preview`` on the running event loop.

    Used by the create endpoint and by startup reconciliation. ``app`` is
    the FastAPI app (or a test double with the same ``.state`` fields).
    """
    state = app.state
    task = asyncio.create_task(
        watch_preview(
            gen_id=gen_id,
            meshy=state.meshy_client,
            session_factory=state.session_factory,
            models_dir=state.models_dir,
            poll_interval=state.watcher_poll_interval,
        )
    )
    state.background_tasks.add(task)
    task.add_done_callback(state.background_tasks.discard)


def spawn_refine_watcher(app: Any, gen_id: str) -> None:
    """Structural twin of ``spawn_preview_watcher`` for the refine stage."""
    state = app.state
    task = asyncio.create_task(
        watch_refine(
            gen_id=gen_id,
            meshy=state.meshy_client,
            session_factory=state.session_factory,
            models_dir=state.models_dir,
            poll_interval=state.watcher_poll_interval,
        )
    )
    state.background_tasks.add(task)
    task.add_done_callback(state.background_tasks.discard)


def reconcile_in_flight(app: Any) -> None:
    """Respawn watchers for every non-terminal generation in SQLite.

    Called from FastAPI lifespan after ``app.state`` is populated. Policy:
      * ``*_IN_PROGRESS`` (and ``*_PENDING``) **with** a Meshy task id →
        respawn the matching watcher. The watcher reads the id from the row.
      * ``*_PENDING`` **without** a task id → the process died after the
        first commit and before Meshy accepted the task. We do **not**
        retry ``create_*_task`` (that could double-charge if Meshy actually
        accepted and we crashed before writing the id). Mark the row failed
        instead. A failed refine still keeps the preview viewable.
      * Terminal rows → ignored.
    """
    session_factory: SessionFactory = app.state.session_factory
    snapshots: list[tuple[str, GenerationStatus, str | None, str | None]] = []
    with session_factory() as session:
        rows = session.execute(
            select(
                Generation.id,
                Generation.status,
                Generation.preview_task_id,
                Generation.refine_task_id,
            ).where(Generation.status.in_(_IN_FLIGHT))
        ).all()
        snapshots = [
            (row.id, row.status, row.preview_task_id, row.refine_task_id)
            for row in rows
        ]

    if not snapshots:
        return

    log.info("startup reconciliation: %d in-flight generation(s)", len(snapshots))
    for gen_id, status, preview_task_id, refine_task_id in snapshots:
        if status in _PREVIEW_IN_FLIGHT:
            if preview_task_id:
                log.info("respawning preview watcher for %s (%s)", gen_id, status.value)
                spawn_preview_watcher(app, gen_id)
            else:
                log.warning(
                    "preview %s was %s with no Meshy task id; marking failed",
                    gen_id,
                    status.value,
                )
                _finalize_failure(
                    session_factory,
                    gen_id,
                    "Interrupted before Meshy accepted the preview task",
                    target=GenerationStatus.PREVIEW_FAILED,
                )
        elif status in _REFINE_IN_FLIGHT:
            if refine_task_id:
                log.info("respawning refine watcher for %s (%s)", gen_id, status.value)
                spawn_refine_watcher(app, gen_id)
            else:
                log.warning(
                    "refine %s was %s with no Meshy task id; marking failed",
                    gen_id,
                    status.value,
                )
                _finalize_failure(
                    session_factory,
                    gen_id,
                    "Interrupted before Meshy accepted the refine task",
                    target=GenerationStatus.REFINE_FAILED,
                )


def maybe_reconcile_in_flight(app: Any) -> None:
    """Lifespan entry: skip when tests set ``TEXT3D_SKIP_RECONCILE=1``."""
    if os.environ.get(SKIP_RECONCILE_ENV) == "1":
        log.debug("startup reconciliation skipped (%s=1)", SKIP_RECONCILE_ENV)
        return
    reconcile_in_flight(app)
