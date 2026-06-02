"""Integration test: the Alembic baseline builds the full schema on an empty DB."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app.core.db_migrate import run_migrations

_EXPECTED_TABLES = {
    "quiz",
    "dimension",
    "question",
    "answeroption",
    "resulttier",
    "quizlandingconfig",
    "quizresultconfig",
    "submission",
}


def test_migration_creates_all_tables(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    run_migrations(engine)

    tables = set(inspect(engine).get_table_names())
    assert _EXPECTED_TABLES <= tables
    assert "alembic_version" in tables


def test_migration_is_idempotent(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    run_migrations(engine)
    # Re-running to head on an already-migrated DB must be a clean no-op.
    run_migrations(engine)
    assert _EXPECTED_TABLES <= set(inspect(engine).get_table_names())
