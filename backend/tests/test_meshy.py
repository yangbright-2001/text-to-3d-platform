"""Tests for the M3 Meshy client.

All Meshy HTTP calls are intercepted by ``respx``; no real API credits are
consumed. See ``PLAN.md`` for the testing strategy.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.meshy import (
    DEFAULT_PREVIEW_AI_MODEL,
    DEFAULT_REFINE_TEXTURE_RESOLUTION,
    MeshyClient,
    MeshyError,
    MeshyTask,
)


API_BASE = "https://api.example.test"
TASK_ID = "018a210d-8ba4-705c-b111-1f1776f7f578"


async def _make_client() -> MeshyClient:
    """Client pointed at a fake base so respx routes match unambiguously."""
    return MeshyClient(api_key="test-key", api_base=API_BASE)


# ---------------------------------------------------------------------------
# Create tasks
# ---------------------------------------------------------------------------


@respx.mock
async def test_create_preview_task_sends_expected_payload_and_returns_id() -> None:
    route = respx.post(f"{API_BASE}/openapi/v2/text-to-3d").mock(
        return_value=httpx.Response(200, json={"result": TASK_ID})
    )

    client = await _make_client()
    result = await client.create_preview_task("a monster mask")
    await client.aclose()

    assert result == TASK_ID
    # Exactly one call, with our payload defaults + bearer auth.
    assert route.called and route.call_count == 1
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer test-key"
    body = _json(sent)
    assert body["mode"] == "preview"
    assert body["prompt"] == "a monster mask"
    assert body["ai_model"] == DEFAULT_PREVIEW_AI_MODEL
    assert body["target_formats"] == ["glb"]


@respx.mock
async def test_create_refine_task_sends_preview_task_id() -> None:
    route = respx.post(f"{API_BASE}/openapi/v2/text-to-3d").mock(
        return_value=httpx.Response(200, json={"result": "refine-id-xyz"})
    )

    client = await _make_client()
    result = await client.create_refine_task(TASK_ID)
    await client.aclose()

    assert result == "refine-id-xyz"
    body = _json(route.calls.last.request)
    assert body["mode"] == "refine"
    assert body["preview_task_id"] == TASK_ID
    # Defaults reflect the "lowest-cost" policy: PBR off, 2k textures, GLB only.
    assert body["enable_pbr"] is False
    assert body["texture_resolution"] == DEFAULT_REFINE_TEXTURE_RESOLUTION
    assert body["target_formats"] == ["glb"]


@respx.mock
async def test_create_preview_raises_meshy_error_on_400() -> None:
    respx.post(f"{API_BASE}/openapi/v2/text-to-3d").mock(
        return_value=httpx.Response(400, json={"message": "prompt too long"})
    )

    client = await _make_client()
    with pytest.raises(MeshyError) as excinfo:
        await client.create_preview_task("x")
    await client.aclose()

    assert excinfo.value.status_code == 400
    assert excinfo.value.body == {"message": "prompt too long"}


# ---------------------------------------------------------------------------
# Get task
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_task_parses_in_progress() -> None:
    """PENDING/IN_PROGRESS responses may omit ``model_urls`` etc."""
    respx.get(f"{API_BASE}/openapi/v2/text-to-3d/{TASK_ID}").mock(
        return_value=httpx.Response(
            200,
            json={"id": TASK_ID, "status": "IN_PROGRESS", "progress": 40},
        )
    )

    client = await _make_client()
    task = await client.get_task(TASK_ID)
    await client.aclose()

    assert isinstance(task, MeshyTask)
    assert task.id == TASK_ID
    assert task.status == "IN_PROGRESS"
    assert task.progress == 40
    assert task.model_urls == {}
    assert task.thumbnail_url is None
    assert task.error_message is None


@respx.mock
async def test_get_task_parses_succeeded_with_urls() -> None:
    respx.get(f"{API_BASE}/openapi/v2/text-to-3d/{TASK_ID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": TASK_ID,
                "status": "SUCCEEDED",
                "progress": 100,
                "model_urls": {"glb": "https://cdn.example/model.glb?Expires=1"},
                "thumbnail_url": "https://cdn.example/preview.png?Expires=1",
                # Empty error message must be normalized to None.
                "task_error": {"message": ""},
            },
        )
    )

    client = await _make_client()
    task = await client.get_task(TASK_ID)
    await client.aclose()

    assert task.status == "SUCCEEDED"
    assert task.progress == 100
    assert task.model_urls == {"glb": "https://cdn.example/model.glb?Expires=1"}
    assert task.thumbnail_url == "https://cdn.example/preview.png?Expires=1"
    assert task.error_message is None


@respx.mock
async def test_get_task_surfaces_failure_message() -> None:
    respx.get(f"{API_BASE}/openapi/v2/text-to-3d/{TASK_ID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": TASK_ID,
                "status": "FAILED",
                "progress": 0,
                "task_error": {"message": "content moderation blocked"},
            },
        )
    )

    client = await _make_client()
    task = await client.get_task(TASK_ID)
    await client.aclose()

    assert task.status == "FAILED"
    assert task.error_message == "content moderation blocked"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


@respx.mock
async def test_download_to_writes_bytes_and_omits_auth_header(tmp_path) -> None:
    payload = b"GLB_BINARY_BYTES_" * 1024  # ~16KB to exercise streaming
    url = "https://cdn.example/model.glb?Expires=1&Signature=abc"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=payload))

    client = await _make_client()
    dest = tmp_path / "sub" / "model.glb"
    await client.download_to(url, dest)
    await client.aclose()

    # File written correctly (also proves ``parents=True`` created ``sub/``).
    assert dest.read_bytes() == payload
    # Presigned URL: no Authorization header must be sent.
    sent = route.calls.last.request
    assert "authorization" not in {k.lower() for k in sent.headers.keys()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(request: httpx.Request) -> dict:
    """Decode a request body as JSON (respx stores raw bytes)."""
    import json

    return json.loads(request.content.decode() or "{}")
