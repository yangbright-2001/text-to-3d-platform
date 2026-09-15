"""Tests for the M1 health endpoint."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    """Health endpoint returns 200 and a well-formed status payload."""
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "text-to-3d-backend"
    # The key flag must be a string boolean and must never leak the key value.
    assert body["meshy_key_configured"] in {"true", "false"}
