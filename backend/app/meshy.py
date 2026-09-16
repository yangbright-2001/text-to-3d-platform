"""Meshy Text-to-3D API client.

The only module in the codebase that knows Meshy's HTTP endpoints, request
shapes, or response fields. Everything else depends on the small surface
exported here: ``MeshyClient``, ``MeshyTask``, and ``MeshyError``. Tests mock
this module's HTTP calls via ``respx`` so no real API credits are consumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from .config import get_settings

# ---------------------------------------------------------------------------
# Meshy-specific policy defaults.
#
# These live next to the client (not in ``config.py``) because they are policy
# decisions about *which* Meshy features to use, not env-tunable operational
# knobs. Changing a value here changes it project-wide. Per PLAN.md we pick the
# lowest-cost non-deprecated standard model and GLB-only output.
# ---------------------------------------------------------------------------
DEFAULT_PREVIEW_AI_MODEL = "meshy-6-lite"
DEFAULT_TARGET_FORMATS: tuple[str, ...] = ("glb",)
DEFAULT_REFINE_ENABLE_PBR = False
DEFAULT_REFINE_TEXTURE_RESOLUTION = "2k"
DEFAULT_REQUEST_TIMEOUT_S = 30.0

# Text-to-3D endpoint path (v2). Both preview and refine hit the same URL and
# are distinguished by the ``mode`` field in the request body.
_TEXT_TO_3D_PATH = "/openapi/v2/text-to-3d"


class MeshyError(Exception):
    """Raised on any non-2xx response from Meshy.

    Carries the HTTP status code and the parsed body (or raw text) so the
    caller — and log lines — can see what went wrong without having to poke
    at ``httpx.Response`` objects.
    """

    def __init__(self, status_code: int, body: object) -> None:
        super().__init__(f"Meshy API error {status_code}: {body!r}")
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class MeshyTask:
    """A read-only snapshot of a Meshy task, decoupled from the raw JSON.

    Only the fields we actually use are surfaced. Extra fields Meshy returns
    are ignored; missing optional fields default to sensible values so callers
    do not have to null-check everything.
    """

    id: str
    status: str  # PENDING | IN_PROGRESS | SUCCEEDED | FAILED | CANCELED
    progress: int
    model_urls: dict[str, str] = field(default_factory=dict)
    thumbnail_url: Optional[str] = None
    error_message: Optional[str] = None


def _raise_for_status(response: httpx.Response) -> None:
    """Convert Meshy HTTP errors into ``MeshyError`` with a useful body."""
    if response.status_code < 400:
        return
    try:
        body: object = response.json()
    except ValueError:
        # Non-JSON error bodies (rare) — keep the raw text for debugging.
        body = response.text
    raise MeshyError(response.status_code, body)


class MeshyClient:
    """Thin async wrapper around the Meshy Text-to-3D v2 API.

    Owns its own ``httpx.AsyncClient`` by default so simple callers can
    instantiate ``MeshyClient(...)`` and use it as an async context manager.
    Retries/backoff are intentionally NOT here — that policy belongs to the
    watcher (M4) which knows the task lifecycle.
    """

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://api.meshy.ai",
        timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key
        # Normalize the base so callers can pass with or without a trailing slash.
        self._api_base = api_base.rstrip("/")
        # If the caller injects an ``AsyncClient`` we do not own its lifecycle;
        # otherwise we manage one and close it in ``aclose``.
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_http = http_client is None

    async def __aenter__(self) -> "MeshyClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_http:
            await self._http.aclose()

    # -- Auth ---------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Bearer auth header. The key never leaves the backend."""
        return {"Authorization": f"Bearer {self._api_key}"}

    # -- Create tasks -------------------------------------------------------

    async def create_preview_task(
        self,
        prompt: str,
        *,
        ai_model: str = DEFAULT_PREVIEW_AI_MODEL,
        target_formats: tuple[str, ...] | list[str] = DEFAULT_TARGET_FORMATS,
    ) -> str:
        """Create a preview task and return the Meshy task id.

        Preview is the mandatory first stage: geometry-only, cheapest model.
        """
        payload: dict[str, object] = {
            "mode": "preview",
            "prompt": prompt,
            "ai_model": ai_model,
            "target_formats": list(target_formats),
        }
        response = await self._http.post(
            f"{self._api_base}{_TEXT_TO_3D_PATH}",
            json=payload,
            headers=self._auth_headers(),
        )
        _raise_for_status(response)
        # Meshy returns ``{"result": "<task-id>"}`` on success for both modes.
        return response.json()["result"]

    async def create_refine_task(
        self,
        preview_task_id: str,
        *,
        enable_pbr: bool = DEFAULT_REFINE_ENABLE_PBR,
        texture_resolution: str = DEFAULT_REFINE_TEXTURE_RESOLUTION,
        target_formats: tuple[str, ...] | list[str] = DEFAULT_TARGET_FORMATS,
    ) -> str:
        """Create a refine task for an already-succeeded preview.

        Refine is only invoked from an explicit user action (see PLAN.md); the
        client itself does not enforce this — the endpoint layer will.
        """
        payload: dict[str, object] = {
            "mode": "refine",
            "preview_task_id": preview_task_id,
            "enable_pbr": enable_pbr,
            "texture_resolution": texture_resolution,
            "target_formats": list(target_formats),
        }
        response = await self._http.post(
            f"{self._api_base}{_TEXT_TO_3D_PATH}",
            json=payload,
            headers=self._auth_headers(),
        )
        _raise_for_status(response)
        return response.json()["result"]

    # -- Read task ----------------------------------------------------------

    async def get_task(self, task_id: str) -> MeshyTask:
        """Fetch the current state of a task (preview or refine)."""
        response = await self._http.get(
            f"{self._api_base}{_TEXT_TO_3D_PATH}/{task_id}",
            headers=self._auth_headers(),
        )
        _raise_for_status(response)
        data = response.json()
        # ``task_error`` is always present but may contain an empty ``message``
        # even for successful tasks — normalize to ``None`` in that case.
        error_message = ((data.get("task_error") or {}).get("message")) or None
        return MeshyTask(
            id=data["id"],
            status=data["status"],
            progress=int(data.get("progress", 0)),
            model_urls=data.get("model_urls") or {},
            thumbnail_url=data.get("thumbnail_url"),
            error_message=error_message,
        )

    # -- Download presigned model / thumbnail URLs --------------------------

    async def download_to(self, url: str, dest: Path) -> None:
        """Stream a presigned Meshy asset URL to ``dest`` on local disk.

        ``model_urls``/``thumbnail_url`` values already carry a signature in
        the query string; we deliberately do NOT attach the ``Authorization``
        header here because some CDNs reject requests that combine both.
        Streamed to disk so multi-MB GLBs don't sit in memory.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._http.stream("GET", url) as response:
            _raise_for_status(response)
            with dest.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)


def get_meshy_client() -> MeshyClient:
    """Factory used later by FastAPI dependency injection (M4).

    Kept here so tests and callers have a single place to construct a client
    from application settings.
    """
    settings = get_settings()
    return MeshyClient(api_key=settings.meshy_api_key, api_base=settings.meshy_api_base)
