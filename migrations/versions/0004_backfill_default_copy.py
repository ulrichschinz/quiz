"""Backfill good default copy into existing quizzes (0004).

New quizzes get sensible German + English defaults straight from the model
(`quizzes/defaults.py`). Quizzes created *before* those defaults existed have
blank generic copy fields (intro, hero, CTA, …). This one-off data migration
fills only the *empty* fields on existing rows, so an older quiz reads as well
as a freshly created one — without ever clobbering copy that's already there.

Defaults are inlined (frozen) so the migration stays self-contained, mirroring
0002/0003. No schema change; pure backfill, safe to run on any DB.

Revision ID: 0004_backfill_default_copy
Revises: 0003_email_body_bilingual
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0004_backfill_default_copy"
down_revision = "0003_email_body_bilingual"
branch_labels = None
depends_on = None

# Frozen snapshot of quizzes/defaults.py at authoring time.
_RESULT_DEFAULTS = {
    "intro_de": "Dein persönliches Ergebnis",
    "intro_en": "Your personal result",
    "email_subject_de": "Dein Ergebnis: {score}/100 — Agentic Reach",
    "email_subject_en": "Your result: {score}/100 — Agentic Reach",
    "notify_emails": "leads@agentic-reach.com",
}
_LANDING_DEFAULTS = {
    "hero_eyebrow_de": "// Agentic Reach",
    "hero_eyebrow_en": "// Agentic Reach",
    "hero_headline_de": "Wie zukunftsfähig ist deine Organisation?",
    "hero_headline_en": "How future-ready is your organization?",
    "hero_subline_de": (
        "In wenigen Minuten herausfinden — kostenlos, unverbindlich und mit "
        "konkreten nächsten Schritten."
    ),
    "hero_subline_en": (
        "Find out in just a few minutes — free, non-binding, and with concrete next steps."
    ),
    "cta_label_de": "Quiz starten →",
    "cta_label_en": "Start the quiz →",
}
_BENEFITS_JSON = json.dumps(
    [
        {"de": "In wenigen Minuten erledigt", "en": "Done in just a few minutes"},
        {"de": "Sofort-Score von 0–100", "en": "Instant score from 0–100"},
        {"de": "Konkrete nächste Schritte", "en": "Concrete next steps"},
    ],
    ensure_ascii=False,
)


def _fill_empty(bind, table: str, defaults: dict[str, str]) -> None:
    columns = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    for col, value in defaults.items():
        if col in columns:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {col} = :v WHERE {col} IS NULL OR {col} = ''"  # noqa: S608
                ),
                {"v": value},
            )


def upgrade() -> None:
    bind = op.get_bind()
    _fill_empty(bind, "quizresultconfig", _RESULT_DEFAULTS)
    _fill_empty(bind, "quizlandingconfig", _LANDING_DEFAULTS)
    # Benefits: also treat the legacy empty-list default as "blank".
    bind.execute(
        sa.text(
            "UPDATE quizlandingconfig SET benefits_json = :v "
            "WHERE benefits_json IS NULL OR benefits_json = '' OR benefits_json = '[]'"
        ),
        {"v": _BENEFITS_JSON},
    )


def downgrade() -> None:
    # Pure data backfill — nothing to reverse (we can't tell filled-by-us apart
    # from authored copy, and clearing would lose real content).
    pass
