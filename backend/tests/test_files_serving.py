"""Tests for the M5 ``GET /files/{path}`` static-file endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture()
def app_with_models_dir(tmp_path):
    """Point ``app.state.models_dir`` at a per-test temp directory."""
    app.state.models_dir = tmp_path
    yield app


async def test_files_endpoint_serves_bytes_from_models_dir(
    app_with_models_dir, tmp_path,
) -> None:
    """A file under ``models_dir`` is served verbatim at the matching URL."""
    subdir = tmp_path / "abc123"
    subdir.mkdir()
    (subdir / "preview.glb").write_bytes(b"FAKE_GLB_BYTES")

    async with AsyncClient(
        transport=ASGITransport(app=app_with_models_dir), base_url="http://test"
    ) as c:
        r = await c.get("/files/abc123/preview.glb")

    assert r.status_code == 200
    assert r.content == b"FAKE_GLB_BYTES"


async def test_files_endpoint_404_when_missing(app_with_models_dir) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_with_models_dir), base_url="http://test"
    ) as c:
        r = await c.get("/files/nope/nothing.glb")
    assert r.status_code == 404


async def test_files_endpoint_rejects_absolute_paths(
    app_with_models_dir, tmp_path,
) -> None:
    """An attempt to reach a file above ``models_dir`` must not leak it.

    ``{path:path}`` captures whatever comes after ``/files/`` verbatim, so
    sending ``/files//etc/passwd`` reaches the handler with ``path='/etc/passwd'``.
    Joining that to ``models_dir`` and resolving would produce ``/etc/passwd``,
    which is not inside ``models_dir`` — the containment check rejects it.
    """
    # Create a "secret" file OUTSIDE the served directory.
    secret = tmp_path.parent / "outside.txt"
    secret.write_bytes(b"top secret")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_with_models_dir), base_url="http://test"
        ) as c:
            # A leading slash on the captured path makes it "absolute" once
            # joined with ``models_dir`` — the defense must still catch it.
            r = await c.get(f"/files/{secret}")
        assert r.status_code == 404
    finally:
        secret.unlink(missing_ok=True)
