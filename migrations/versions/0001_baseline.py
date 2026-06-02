"""Baseline — the current create_all schema, captured verbatim.

Baseline migration = current schema, no data change. Rather than hand-writing
~8 `op.create_table` blocks (drift risk), it delegates to the exact schema
builder the app uses: `SQLModel.metadata.create_all(bind)` after importing
every domain's models via `app.tables`. That makes the captured schema
byte-identical to the in-process create_all by construction.

All DDL runs on Alembic's own migration connection (`op.get_bind()`).
Idempotent: `create_all` is checkfirst.

Revision ID: 0001_baseline
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlmodel import SQLModel

    import app.tables  # noqa: F401  registers every domain table on the metadata

    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)


def downgrade() -> None:
    from sqlmodel import SQLModel

    import app.tables  # noqa: F401

    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind)
