"""Pydantic schemas for the HTTP API.

Kept intentionally minimal and read-only-from-the-client's-perspective:
internal fields like Meshy task ids and the Meshy request-parameter snapshot
are NOT exposed on the wire. File locations are surfaced as ``/files/...``
URLs (served by the backend itself) rather than raw filesystem paths or Meshy
presigned URLs — see PLAN.md's contract that "clients only ever receive our
own file URLs".
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from .models import GenerationStatus

if TYPE_CHECKING:  # pragma: no cover — for type hints only
    from .models import Generation


class GenerationCreate(BaseModel):
    """Request body for ``POST /api/generations``.

    Meshy caps preview prompts at 800 characters; we enforce that on the
    boundary so users get a helpful 422 rather than a downstream Meshy 400.
    """

    prompt: str = Field(..., min_length=1, max_length=800)


class GenerationRead(BaseModel):
    """Response representation of a generation.

    Field naming: DB columns end in ``_path`` (relative filesystem paths under
    ``models_dir``); the API instead exposes ``_url`` fields under our own
    ``/files/...`` mount so the frontend never sees raw paths or Meshy URLs.
    """

    id: str
    prompt: str
    status: GenerationStatus
    error: Optional[str] = None
    preview_progress: int
    preview_model_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    refine_progress: int
    refine_model_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_generation(cls, gen: "Generation") -> "GenerationRead":
        """Build a wire representation from a ``Generation`` ORM row.

        This is the single spot that translates internal ``_path`` values into
        public ``/files/...`` URLs — endpoints never build these strings by hand.
        """
        return cls(
            id=gen.id,
            prompt=gen.prompt,
            status=gen.status,
            error=gen.error,
            preview_progress=gen.preview_progress,
            preview_model_url=_files_url(gen.preview_model_path),
            thumbnail_url=_thumbnail_url(gen.thumbnail_path, gen.updated_at),
            refine_progress=gen.refine_progress,
            refine_model_url=_files_url(gen.refine_model_path),
            created_at=gen.created_at,
            updated_at=gen.updated_at,
        )


def _files_url(relative_path: Optional[str]) -> Optional[str]:
    """Prepend the app's static-files mount to a relative asset path."""
    return f"/files/{relative_path}" if relative_path else None


def _thumbnail_url(relative_path: Optional[str], updated_at: datetime) -> Optional[str]:
    """Like ``_files_url`` but cache-busted with ``updated_at``.

    Preview and refine overwrite the same ``thumbnail.png`` path. Without a
    changing query string the browser keeps showing the preview thumbnail
    after a successful refine.
    """
    if not relative_path:
        return None
    token = updated_at.strftime("%Y%m%d%H%M%S")
    return f"/files/{relative_path}?v={token}"
