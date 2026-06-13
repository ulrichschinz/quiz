"""Bilingual result e-mail body (0003).

The result e-mail subject was already per-language (`email_subject_de/en`) but
the body was a single `email_body_template` — so a quiz taken in English still
sent a German e-mail. This splits the body into `email_body_de` / `email_body_en`
and gives the English column a good default for rows that only had the legacy
(German) template.

Idempotent against the create_all baseline (which already declares the two new
columns and no longer declares `email_body_template`): on a brand-new DB the
column adds/drop are guarded no-ops; on the live DB (created before this change)
they run for real. Mirrors the guarded style of 0002.

Revision ID: 0003_email_body_bilingual
Revises: 0002_option_rank_and_dim_percent
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_email_body_bilingual"
down_revision = "0002_option_rank_and_dim_percent"
branch_labels = None
depends_on = None

# Inlined (frozen) so the migration stays self-contained, like 0002's weight fn.
_DEFAULT_EMAIL_BODY_EN = (
    "Hi {name},\n\n"
    "thank you for taking the time to complete our survey. "
    "Here is your result: {score}/100 — {tier}.\n\n"
    "Your full evaluation, including concrete next steps, is available here:\n"
    "{url}\n\n"
    "If you'd like to go through the results together, feel free to reach out any time.\n\n"
    "Best regards,\n"
    "The Agentic Reach team"
)


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("quizresultconfig")}

    if "email_body_de" not in columns:
        op.add_column(
            "quizresultconfig",
            sa.Column("email_body_de", sa.String(), nullable=False, server_default=""),
        )
        if "email_body_template" in columns:  # carry the legacy body over verbatim
            bind.execute(
                sa.text("UPDATE quizresultconfig SET email_body_de = email_body_template")
            )

    if "email_body_en" not in columns:
        op.add_column(
            "quizresultconfig",
            sa.Column("email_body_en", sa.String(), nullable=False, server_default=""),
        )

    # Give every row that lacks an English body a sensible default (covers the
    # renamed legacy rows that only ever had a German template).
    bind.execute(
        sa.text(
            "UPDATE quizresultconfig SET email_body_en = :en "
            "WHERE email_body_en IS NULL OR email_body_en = ''"
        ),
        {"en": _DEFAULT_EMAIL_BODY_EN},
    )

    if "email_body_template" in columns:  # native DROP COLUMN, as in 0002
        op.drop_column("quizresultconfig", "email_body_template")


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("quizresultconfig")}

    if "email_body_template" not in columns:
        op.add_column(
            "quizresultconfig",
            sa.Column("email_body_template", sa.String(), nullable=False, server_default=""),
        )
        if "email_body_de" in columns:
            bind.execute(
                sa.text("UPDATE quizresultconfig SET email_body_template = email_body_de")
            )

    for col_name in ("email_body_de", "email_body_en"):
        if col_name in columns:
            op.drop_column("quizresultconfig", col_name)
