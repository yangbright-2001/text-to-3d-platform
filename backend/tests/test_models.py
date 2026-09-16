"""Tests for the M2 persistence layer and status state machine."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Generation, GenerationStatus, can_transition


def test_generation_defaults(session: Session) -> None:
    """A minimal insert should populate id/status/progress/timestamps/JSON."""
    gen = Generation(prompt="a monster mask")
    session.add(gen)
    session.commit()
    session.refresh(gen)

    # UUID-shaped app-level id.
    assert isinstance(gen.id, str)
    uuid.UUID(gen.id)  # raises if not a valid UUID

    assert gen.prompt == "a monster mask"
    assert gen.status is GenerationStatus.PREVIEW_PENDING
    assert gen.preview_progress == 0
    assert gen.refine_progress == 0
    assert gen.preview_task_id is None
    assert gen.refine_task_id is None
    assert gen.error is None
    # JSON column defaults to an empty dict, not a shared mutable.
    assert gen.meshy_params == {}
    # Timestamps set on insert and equal at creation time.
    assert gen.created_at is not None
    assert gen.updated_at is not None


def test_updated_at_advances_on_change(session: Session) -> None:
    """Mutating a row should push ``updated_at`` forward (onupdate fires)."""
    gen = Generation(prompt="p")
    session.add(gen)
    session.commit()
    session.refresh(gen)
    first_updated = gen.updated_at

    # Sleep briefly so timestamp resolution is enough to see a change.
    time.sleep(0.01)
    gen.status = GenerationStatus.PREVIEW_IN_PROGRESS
    gen.preview_progress = 25
    session.commit()
    session.refresh(gen)

    assert gen.updated_at > first_updated
    assert gen.status is GenerationStatus.PREVIEW_IN_PROGRESS


def test_meshy_params_json_roundtrip(session: Session) -> None:
    """The JSON column should preserve nested dict/list structures."""
    params = {"ai_model": "meshy-6-lite", "target_formats": ["glb"], "should_remesh": False}
    gen = Generation(prompt="p", meshy_params=params)
    session.add(gen)
    session.commit()

    # Re-read through the ORM to prove the roundtrip goes through SQLite.
    loaded = session.scalar(select(Generation).where(Generation.id == gen.id))
    assert loaded is not None
    assert loaded.meshy_params == params


def test_status_transitions_allowed() -> None:
    """The full happy path (preview -> refine) is explicitly allowed."""
    happy_path = [
        (GenerationStatus.PREVIEW_PENDING, GenerationStatus.PREVIEW_IN_PROGRESS),
        (GenerationStatus.PREVIEW_IN_PROGRESS, GenerationStatus.PREVIEW_SUCCEEDED),
        (GenerationStatus.PREVIEW_SUCCEEDED, GenerationStatus.REFINE_PENDING),
        (GenerationStatus.REFINE_PENDING, GenerationStatus.REFINE_IN_PROGRESS),
        (GenerationStatus.REFINE_IN_PROGRESS, GenerationStatus.REFINE_SUCCEEDED),
    ]
    for src, dst in happy_path:
        assert can_transition(src, dst), f"expected {src} -> {dst} to be allowed"

    # Failure edges are also allowed from the two in-progress states.
    assert can_transition(GenerationStatus.PREVIEW_IN_PROGRESS, GenerationStatus.PREVIEW_FAILED)
    assert can_transition(GenerationStatus.REFINE_IN_PROGRESS, GenerationStatus.REFINE_FAILED)


def test_status_transitions_rejected() -> None:
    """Transitions outside the allow-list must be rejected."""
    # Refine cannot start automatically from a pending preview.
    assert not can_transition(GenerationStatus.PREVIEW_PENDING, GenerationStatus.REFINE_PENDING)
    # Cannot skip the in-progress step.
    assert not can_transition(GenerationStatus.PREVIEW_PENDING, GenerationStatus.PREVIEW_SUCCEEDED)
    # Refine only starts from a succeeded preview (never from failed).
    assert not can_transition(GenerationStatus.PREVIEW_FAILED, GenerationStatus.REFINE_PENDING)
    # Terminal states are terminal — no going back.
    assert not can_transition(
        GenerationStatus.REFINE_SUCCEEDED, GenerationStatus.PREVIEW_PENDING
    )
    assert not can_transition(
        GenerationStatus.REFINE_FAILED, GenerationStatus.REFINE_IN_PROGRESS
    )
