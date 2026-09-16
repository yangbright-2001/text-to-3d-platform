"""Pydantic schemas for the HTTP API.

Kept intentionally minimal and read-only-from-the-client's-perspective:
internal fields like Meshy task ids and the Meshy request-parameter snapshot
are NOT exposed on the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import GenerationStatus


class GenerationCreate(BaseModel):
    """Request body for ``POST /api/generations``.

    Meshy caps preview prompts at 800 characters; we enforce that on the
    boundary so users get a helpful 422 rather than a downstream Meshy 400.
    """

    prompt: str = Field(..., min_length=1, max_length=800)


class GenerationRead(BaseModel):
    """Response representation of a generation.

    Deliberately omits ``preview_task_id`` / ``refine_task_id`` / ``meshy_params``:
    those are internal implementation details the frontend must not depend on.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    prompt: str
    status: GenerationStatus
    error: Optional[str] = None
    preview_progress: int
    preview_model_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    refine_progress: int
    refine_model_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
