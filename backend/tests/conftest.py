"""Shared pytest fixtures.

Automated tests never touch the production ``data/app.db``. Each test gets a
fresh in-memory SQLite database via SQLAlchemy's ``StaticPool``, which pins
all sessions to the same connection so the ephemeral in-memory DB is visible
across the test's operations.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base


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
