"""Database engine, session, and initialization.

Sync SQLAlchemy 2.0 wired to a single on-disk SQLite file. Kept intentionally
small: one engine, one ``SessionLocal``, one FastAPI dependency, and an
``init_db`` helper that creates directories + tables. Tests do not use these
module-level singletons — they build their own engine/session in
``tests/conftest.py`` (see the test database isolation section in ``PLAN.md``).
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


settings = get_settings()

# ``check_same_thread=False`` lets FastAPI's threadpool (used for sync routes)
# and future background watcher tasks safely share the engine; per-request
# sessions still isolate transactions.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped SQLAlchemy session.

    Tests override this dependency via ``app.dependency_overrides`` so that
    automated tests never touch the production ``data/app.db``.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create the data directory and all tables if they do not yet exist.

    Called from the FastAPI lifespan on startup. Safe to call repeatedly; it
    is idempotent by design (SQLAlchemy's ``create_all`` and ``mkdir`` with
    ``exist_ok``).
    """
    # Ensure the on-disk locations for the SQLite file and downloaded model
    # files exist before any code tries to write to them.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)

    # Import models so their tables are registered on ``Base.metadata`` before
    # we call ``create_all``. Imported here (not at module top) to avoid a
    # circular import between ``db`` and ``models``.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
