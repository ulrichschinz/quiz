"""Option ranking + percent dimension shares (weighting redesign 0002).

Adds `answeroption.score_rank` (0 = best answer) as the source of truth for an
option's value and backfills it from the legacy `weight` floats; the weight is
then re-derived from the rank so duplicate/missing-max weights can't survive.
Dimension `weight` becomes a percent share — every quiz's dimensions are
renormalised to sum 100.

Idempotent against the create_all baseline: a brand-new DB builds `answeroption`
*with* `score_rank` already (the model now declares it), so the column add is
guarded by an inspector check and the backfills are no-ops on empty tables. On
the live DB (created before this column existed) the add + backfills run for
real.

Revision ID: 0002_option_rank_and_dim_percent
Revises: 0001_baseline
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_option_rank_and_dim_percent"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _weight_for_rank(rank: int, n: int) -> float:
    """Mirror of app.domains.quizzes.scoring.weight_for_rank (kept inline so the
    migration stays self-contained and frozen against future code changes)."""
    if n <= 1:
        return 1.0
    rank = max(0, min(rank, n - 1))
    return (n - 1 - rank) / (n - 1)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    columns = {c["name"] for c in insp.get_columns("answeroption")}
    if "score_rank" not in columns:
        op.add_column(
            "answeroption",
            sa.Column("score_rank", sa.Integer(), nullable=False, server_default="0"),
        )

    # Backfill ranks + derived weights per question (no-op on an empty table).
    rows = bind.execute(
        sa.text("SELECT id, question_id, weight, position FROM answeroption")
    ).fetchall()
    by_question: dict[int, list[sa.Row]] = {}
    for row in rows:
        by_question.setdefault(row.question_id, []).append(row)
    for options in by_question.values():
        # Best answer first: highest legacy weight, ties keep their display order.
        ordered = sorted(options, key=lambda r: (-(r.weight or 0.0), r.position, r.id))
        n = len(ordered)
        for rank, row in enumerate(ordered):
            bind.execute(
                sa.text(
                    "UPDATE answeroption SET score_rank = :rank, weight = :weight WHERE id = :id"
                ),
                {"rank": rank, "weight": _weight_for_rank(rank, n), "id": row.id},
            )

    # Renormalise each quiz's dimension weights to percent shares summing to 100.
    dims = bind.execute(sa.text("SELECT id, quiz_id, weight FROM dimension")).fetchall()
    by_quiz: dict[int, list[sa.Row]] = {}
    for d in dims:
        by_quiz.setdefault(d.quiz_id, []).append(d)
    for group in by_quiz.values():
        total = sum(d.weight or 0.0 for d in group)
        n = len(group)
        if total <= 0:
            shares = [round(100 / n, 1) for _ in group]
        else:
            shares = [round((d.weight or 0.0) / total * 100, 1) for d in group]
        drift = round(100 - sum(shares), 1)
        if drift:
            biggest = max(range(n), key=lambda i: shares[i])
            shares[biggest] = round(shares[biggest] + drift, 1)
        for d, share in zip(group, shares, strict=True):
            bind.execute(
                sa.text("UPDATE dimension SET weight = :weight WHERE id = :id"),
                {"weight": share, "id": d.id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("answeroption")}
    if "score_rank" in columns:
        op.drop_column("answeroption", "score_rank")
