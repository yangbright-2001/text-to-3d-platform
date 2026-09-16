"""Shared pytest fixtures + a ``FakeMeshyClient`` used across watcher and
endpoint tests.

Automated tests never touch the production ``data/app.db``. Each test gets a
fresh in-memory SQLite database via SQLAlchemy's ``StaticPool``, which pins
all sessions to the same connection so the ephemeral in-memory DB is visible
across the test's operations.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# Prevent FastAPI lifespan (used by the health TestClient) from scanning the
# developer's on-disk ``data/app.db`` or calling Meshy during pytest.
os.environ.setdefault("TEXT3D_SKIP_RECONCILE", "1")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.meshy import MeshyError, MeshyTask


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """A fresh in-memory SQLite engine with the schema created."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        # StaticPool keeps a single connection alive for the engine's lifetime
        # so that the in-memory DB persists across sessions within one test.
        poolclass=StaticPool,
        future=True,
    )
    # Import models so their tables are registered on Base.metadata.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    """A session bound to the isolated in-memory engine."""
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    sess = TestingSession()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker:
    """A sessionmaker bound to the same in-memory engine as ``session``.

    Watchers use a factory rather than a single session because each
    poll/update should be a short, self-contained transaction.
    """
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# ---------------------------------------------------------------------------
# FakeMeshyClient — a lightweight stand-in for the real ``MeshyClient`` that
# never makes network calls. Used by watcher and endpoint tests to drive the
# full lifecycle deterministically without consuming Meshy credits.
# ---------------------------------------------------------------------------


@dataclass
class FakeMeshyClient:
    """Scriptable Meshy stand-in.

    - ``task_snapshots``: consecutive results returned by ``get_task``. The
      last snapshot is repeated if the watcher polls more times than provided.
    - ``create_task_id``: what ``create_preview_task`` returns.
    - ``create_raises`` / ``get_raises_on_call``: inject errors at specific points.
    """

    task_snapshots: list[MeshyTask] = field(default_factory=list)
    create_task_id: str = "fake-meshy-task-id"
    create_raises: MeshyError | None = None
    get_raises_on_call: int | None = None  # 1-indexed; None means never
    download_content: bytes = b"fake-glb-bytes"

    # Call-tracking so tests can assert what the client was asked to do.
    create_preview_calls: list[str] = field(default_factory=list)
    create_refine_calls: list[str] = field(default_factory=list)
    download_calls: list[tuple[str, Path]] = field(default_factory=list)
    _get_call_count: int = 0

    async def create_preview_task(self, prompt: str, **_: object) -> str:
        self.create_preview_calls.append(prompt)
        if self.create_raises is not None:
            raise self.create_raises
        return self.create_task_id

    async def create_refine_task(self, preview_task_id: str, **_: object) -> str:
        self.create_refine_calls.append(preview_task_id)
        if self.create_raises is not None:
            raise self.create_raises
        return self.create_task_id

    async def get_task(self, task_id: str) -> MeshyTask:
        self._get_call_count += 1
        if (
            self.get_raises_on_call is not None
            and self._get_call_count == self.get_raises_on_call
        ):
            raise MeshyError(500, {"message": "simulated transient meshy error"})
        if not self.task_snapshots:
            raise AssertionError("FakeMeshyClient: no task_snapshots configured")
        idx = min(self._get_call_count - 1, len(self.task_snapshots) - 1)
        return self.task_snapshots[idx]

    async def download_to(self, url: str, dest: Path) -> None:
        self.download_calls.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.download_content)

    async def aclose(self) -> None:
        # No underlying resources; provided so it mirrors MeshyClient's API.
        return None
