"""Alembic environment.

Binding: the in-process runner (`app.core.db_migrate.run_migrations`) stashes
the live engine on `config.attributes["connection"]` — this preserves the
per-test-engine seam. When run from the `alembic` CLI (no stashed connection)
it falls back to the configured database URL.

This file lives under `migrations/`, which is NOT an import-linter root_package
and not in the mypy/ruff scope, so its dynamic Alembic patterns and its
`app.*` reach do not affect any contract.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Engine

config = context.config

# No autogenerate — the 0001 baseline is hand-defined to be the create_all
# schema (byte-identical by delegation). target_metadata stays None.
target_metadata = None

_VERSION_TABLE = config.get_main_option("version_table") or "alembic_version"


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=_VERSION_TABLE,
        render_as_batch=True,  # SQLite-friendly ALTER for future revisions
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        from sqlalchemy import create_engine

        from app.core.config import get_settings

        connectable = create_engine(
            get_settings().database_url, connect_args={"check_same_thread": False}
        )

    if isinstance(connectable, Engine):
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


run_migrations_online()
