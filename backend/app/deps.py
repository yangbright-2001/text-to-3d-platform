"""FastAPI dependency helpers.

Kept in a small dedicated module so the client/model files stay free of any
FastAPI imports (they are otherwise plain-library code).
"""

from __future__ import annotations

from fastapi import Request

from .meshy import MeshyClient


def get_meshy_client(request: Request) -> MeshyClient:
    """Return the app-scoped shared ``MeshyClient`` created in the lifespan.

    Tests override this via ``app.dependency_overrides`` so a FakeMeshyClient
    is used instead — no real Meshy calls are made in the test suite.
    """
    return request.app.state.meshy_client
