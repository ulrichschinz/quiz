"""Quizzes domain — the scoring engine (pure functions).

No FastAPI, no DB, no ORM imports — just arithmetic on plain values, so it is
trivially unit-testable and stays domain-internal. The service layer
(`service.score_submission`) loads the weights/dimensions/tiers from the DB and
calls into here.

Model:
- a question contributes a fraction 0.0–1.0 (the selected option's weight),
- a dimension score (0–100) is the mean of its answered questions' fractions,
- the overall score (0–100) is the dimension-weight-weighted mean of dimensions,
- the tier is the band whose [min, max] contains the overall score.
"""

from __future__ import annotations


def weight_for_rank(rank: int, option_count: int) -> float:
    """Derive an option's 0.0–1.0 weight from its scoring rank.

    Rank 0 is the best answer (full credit), the last rank is the worst (zero).
    Evenly spaced in between, so for 4 options the shares are 1.0 / 0.667 /
    0.333 / 0.0. This is the single source of truth for the option-ranking
    weighting model — the admin service recomputes weights from ranks on every
    change, and the 0002 migration backfills legacy rows with the same formula.

    A single option (or a defensively clamped count) always scores full credit;
    out-of-range ranks are clamped into [0, option_count - 1].
    """
    if option_count <= 1:
        return 1.0
    rank = max(0, min(rank, option_count - 1))
    return (option_count - 1 - rank) / (option_count - 1)


def dimension_score(selected_weights: list[float]) -> int:
    """Mean of the answered options' weights, scaled to 0–100."""
    if not selected_weights:
        return 0
    return round(100 * sum(selected_weights) / len(selected_weights))


def overall_score(dimension_scores: dict[str, int], dimension_weights: dict[str, float]) -> int:
    """Dimension-weight-weighted mean of the per-dimension scores (0–100)."""
    total_weight = sum(dimension_weights.get(key, 0.0) for key in dimension_scores)
    if total_weight <= 0:
        return 0
    weighted = sum(
        score * dimension_weights.get(key, 0.0) for key, score in dimension_scores.items()
    )
    return round(weighted / total_weight)


def resolve_tier(overall: int, tiers: list[tuple[int, int, int]]) -> int | None:
    """Return the id of the first tier whose [min, max] contains `overall`.

    `tiers` is a list of (tier_id, min_score, max_score), pre-ordered by the
    admin's tier position so the lowest position wins on an overlap.
    """
    for tier_id, lo, hi in tiers:
        if lo <= overall <= hi:
            return tier_id
    return None
