"""app.core.db — engine + session dependency + schema bootstrap.

The engine binds to `settings.database_url` (SQLite by default). `create_db()`
is the single schema-establishment entry point called from the app lifespan;
from Phase 2 it delegates to the Alembic runner (`app.core.db_migrate`). The
shared `SQLModel` declarative base is re-exported here so every domain models
module imports it from one place (`from app.core.db import SQLModel`).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, create_engine
from sqlmodel import SQLModel as SQLModel  # explicit re-export: shared base

from app.core.config import get_settings

DATABASE_URL = get_settings().database_url

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def create_db() -> None:
    """Establish the schema by running the Alembic migrations to head.

    Bound to the live `engine` so the per-test-engine seam keeps working. The
    baseline delegates to `create_all`, so this is idempotent on an existing DB.
    """
    from app.core.db_migrate import run_migrations

    run_migrations(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a session bound to the module engine."""
    with Session(engine) as session:
        yield session
