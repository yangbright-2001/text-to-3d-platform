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
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from .meshy import DEFAULT_PREVIEW_AI_MODEL, DEFAULT_TARGET_FORMATS, MeshyClient, MeshyError, MeshyTask
from .models import Generation, GenerationStatus, can_transition

# Default watcher poll interval used in production. Overridden per-app via
# ``app.state.watcher_poll_interval`` so tests can drive the loop instantly.
DEFAULT_POLL_INTERVAL_S = 5.0

# Constant used to advertise the parameters we sent to Meshy — persisted on
# ``Generation.meshy_params`` at creation time so historical rows remain
# self-describing even if defaults change later.
PREVIEW_MESHY_PARAMS: dict[str, object] = {
    "mode": "preview",
    "ai_model": DEFAULT_PREVIEW_AI_MODEL,
    "target_formats": list(DEFAULT_TARGET_FORMATS),
}

log = logging.getLogger(__name__)

# Type alias for the sessionmaker-style callable the watcher accepts. Written
# without importing ``sessionmaker`` explicitly to keep signatures readable.
SessionFactory = Callable[[], Session]


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
    import asyncio  # local import keeps module import cheap for non-async callers

    task_id = _load_preview_task_id(session_factory, gen_id)
    if task_id is None:
        # Row deleted or not yet populated — nothing to do.
        return

    while True:
        try:
            snapshot = await meshy.get_task(task_id)
        except MeshyError as exc:
            # Simple M4 policy: any Meshy error mid-poll is terminal. A future
            # milestone can add bounded retries here if transient 5xx happen.
            log.warning("preview watcher: Meshy error for %s: %s", gen_id, exc)
            _finalize_failure(session_factory, gen_id, f"Meshy error: {exc}")
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


def _apply_preview_snapshot(
    session_factory: SessionFactory, gen_id: str, snapshot: MeshyTask
) -> bool:
    """Persist one Meshy snapshot to the row. Returns True if terminal.

    Terminal here means the polling loop should stop; the caller is
    responsible for the subsequent download step on ``SUCCEEDED``.
    """
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
        _apply_failure(gen, message)
        session.commit()
        return True


def _apply_failure(gen: Generation, message: str) -> None:
    """Move a row to PREVIEW_FAILED (if allowed) and record ``error``."""
    if can_transition(gen.status, GenerationStatus.PREVIEW_FAILED):
        gen.status = GenerationStatus.PREVIEW_FAILED
    gen.error = message


def _finalize_failure(session_factory: SessionFactory, gen_id: str, message: str) -> None:
    """Standalone helper used when failure is discovered outside the snapshot flow."""
    with session_factory() as session:
        gen = session.get(Generation, gen_id)
        if gen is None:
            return
        _apply_failure(gen, message)
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
    """Fetch the GLB (and thumbnail, if present) to local disk and update the row.

    Failure policy:
      * missing / failed GLB download → PREVIEW_FAILED (asset is required for the viewer)
      * failed thumbnail download → keep going; the preview is still viewable
    """
    glb_url = snapshot.model_urls.get("glb")
    if not glb_url:
        _finalize_failure(
            session_factory, gen_id, "Meshy SUCCEEDED but returned no GLB URL"
        )
        return

    # Files live under ``<models_dir>/<gen_id>/`` so all assets for one
    # generation are colocated and easy to serve/list/delete later.
    glb_rel = f"{gen_id}/preview.glb"
    try:
        await meshy.download_to(glb_url, models_dir / glb_rel)
    except MeshyError as exc:
        _finalize_failure(session_factory, gen_id, f"GLB download failed: {exc}")
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
