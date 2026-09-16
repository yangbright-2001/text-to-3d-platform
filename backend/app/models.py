"""ORM models and the application-level task state machine.

One row in ``generations`` = one application-level generation, wrapping the
two Meshy tasks (preview + optional refine) that are otherwise invisible to
users. See ``PLAN.md`` for the state machine diagram this file encodes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class GenerationStatus(str, enum.Enum):
    """Application-level status of a generation.

    A single enum drives both the UI and the watcher logic. Values are stored
    as strings in SQLite so the database is human-readable and stable across
    code refactors.
    """

    PREVIEW_PENDING = "PREVIEW_PENDING"
    PREVIEW_IN_PROGRESS = "PREVIEW_IN_PROGRESS"
    PREVIEW_SUCCEEDED = "PREVIEW_SUCCEEDED"
    PREVIEW_FAILED = "PREVIEW_FAILED"
    REFINE_PENDING = "REFINE_PENDING"
    REFINE_IN_PROGRESS = "REFINE_IN_PROGRESS"
    REFINE_SUCCEEDED = "REFINE_SUCCEEDED"
    REFINE_FAILED = "REFINE_FAILED"


# Allowed transitions in the app-level state machine (see PLAN.md). Anything
# not listed here is rejected by ``can_transition``. Refine only starts from
# ``PREVIEW_SUCCEEDED`` via an explicit user action — never automatically.
_ALLOWED_TRANSITIONS: dict[GenerationStatus, frozenset[GenerationStatus]] = {
    GenerationStatus.PREVIEW_PENDING: frozenset(
        {GenerationStatus.PREVIEW_IN_PROGRESS, GenerationStatus.PREVIEW_FAILED}
    ),
    GenerationStatus.PREVIEW_IN_PROGRESS: frozenset(
        {GenerationStatus.PREVIEW_SUCCEEDED, GenerationStatus.PREVIEW_FAILED}
    ),
    GenerationStatus.PREVIEW_SUCCEEDED: frozenset({GenerationStatus.REFINE_PENDING}),
    GenerationStatus.PREVIEW_FAILED: frozenset(),
    GenerationStatus.REFINE_PENDING: frozenset(
        {GenerationStatus.REFINE_IN_PROGRESS, GenerationStatus.REFINE_FAILED}
    ),
    GenerationStatus.REFINE_IN_PROGRESS: frozenset(
        {GenerationStatus.REFINE_SUCCEEDED, GenerationStatus.REFINE_FAILED}
    ),
    GenerationStatus.REFINE_SUCCEEDED: frozenset(),
    GenerationStatus.REFINE_FAILED: frozenset(),
}


def can_transition(current: GenerationStatus, target: GenerationStatus) -> bool:
    """Return whether moving from ``current`` to ``target`` is allowed.

    Later milestones (M4 preview watcher, M8 refine endpoint) call this before
    mutating status, so illegal transitions can never sneak in from a bug or a
    stray Meshy response.
    """
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


def _utcnow() -> datetime:
    """UTC-aware ``now`` used as the default for timestamp columns."""
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    """Generate a new application-level task id (independent of Meshy's ids)."""
    return str(uuid.uuid4())


class Generation(Base):
    """One user generation: prompt in, preview + optional refine models out.

    Both Meshy task ids live on this single row so the UI never has to show
    preview and refine as separate tasks.
    """

    __tablename__ = "generations"

    # Application-level identifier surfaced to the frontend. Distinct from
    # Meshy's task ids, which are stored separately below.
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus, native_enum=False, length=32),
        nullable=False,
        default=GenerationStatus.PREVIEW_PENDING,
    )
    # Human-readable failure detail; populated on PREVIEW_FAILED / REFINE_FAILED.
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Preview stage — the mandatory first Meshy task.
    preview_task_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    preview_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Relative paths under ``settings.models_dir``; kept relative so moving the
    # data folder or serving from a different mount point is trivial.
    preview_model_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Refine stage — optional, only created when the user explicitly requests it.
    refine_task_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    refine_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refine_model_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Snapshot of the parameters we sent to Meshy (model, formats, etc.), kept
    # for debugging and history. ``default=dict`` avoids a shared-mutable-default.
    meshy_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # ``onupdate`` fires on any SQLAlchemy-driven UPDATE, so the watcher's
    # progress writes will naturally advance ``updated_at``.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
