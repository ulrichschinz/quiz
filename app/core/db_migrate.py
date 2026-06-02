"""app.core.db_migrate — Alembic runner (single tree).

The runner binds Alembic to the **live engine** the app uses (passed in,
stashed on `config.attributes["connection"]` for env.py) rather than
re-deriving the URL — this preserves the per-test-engine seam exactly as an
in-process `create_all` would.

Domain-agnostic by contract (only `alembic` + stdlib + the passed engine), so
the `app.core ↛ domains/interfaces/contracts` import-linter rule stays green.
The baseline migration itself (under `migrations/`, outside the import scope)
imports the models to populate `SQLModel.metadata`.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

# Repo-root/migrations (this file is app/core/db_migrate.py → parents[2]).
_MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations"


def _config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_ROOT))
    # env.py uses this live connectable instead of building one from a URL.
    cfg.attributes["connection"] = engine
    return cfg


def run_migrations(engine: Engine) -> None:
    """Upgrade the schema to head. Idempotent (baseline delegates to create_all)."""
    command.upgrade(_config(engine), "head")
