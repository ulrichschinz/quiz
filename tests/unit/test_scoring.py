"""Unit tests for the pure scoring engine + the DB-backed scoring service."""

from __future__ import annotations

from sqlmodel import Session, select

from app.domains.quizzes import scoring, service
from app.domains.quizzes.models import AnswerOption, Question


def test_weight_for_rank_is_evenly_spaced_best_to_worst() -> None:
    # 4 options: 1.0 / .667 / .333 / 0.0 (rank 0 = best answer)
    assert [round(scoring.weight_for_rank(r, 4), 3) for r in range(4)] == [1.0, 0.667, 0.333, 0.0]
    # 2 options collapse to the extremes
    assert [scoring.weight_for_rank(r, 2) for r in range(2)] == [1.0, 0.0]
    # a single option (or a degenerate count) always scores full credit
    assert scoring.weight_for_rank(0, 1) == 1.0
    # out-of-range ranks clamp instead of going negative / above 1
    assert scoring.weight_for_rank(9, 3) == 0.0
    assert scoring.weight_for_rank(-1, 3) == 1.0


def test_dimension_score_is_mean_scaled_to_100() -> None:
    assert scoring.dimension_score([1.0, 1.0]) == 100
    assert scoring.dimension_score([0.0, 0.0]) == 0
    assert scoring.dimension_score([0.0, 1.0]) == 50
    assert scoring.dimension_score([]) == 0  # no answers → guarded


def test_overall_is_dimension_weighted_mean() -> None:
    scores = {"a": 80, "b": 40}
    assert scoring.overall_score(scores, {"a": 1.0, "b": 1.0}) == 60
    # Weighting dimension "a" 3x pulls the overall toward 80.
    assert scoring.overall_score(scores, {"a": 3.0, "b": 1.0}) == 70
    assert scoring.overall_score({}, {}) == 0  # guarded


def test_resolve_tier_picks_containing_band() -> None:
    tiers = [(1, 0, 49), (2, 50, 100)]
    assert scoring.resolve_tier(20, tiers) == 1
    assert scoring.resolve_tier(50, tiers) == 2
    assert scoring.resolve_tier(101, tiers) is None


def _all_yes_answers(session: Session) -> dict[int, int]:
    """Build {question_id: option_id} choosing the weight-1.0 option each time."""
    answers: dict[int, int] = {}
    for q in session.exec(select(Question)).all():
        yes = session.exec(
            select(AnswerOption).where(
                AnswerOption.question_id == q.id, AnswerOption.weight == 1.0
            )
        ).first()
        assert q.id is not None and yes is not None and yes.id is not None
        answers[q.id] = yes.id
    return answers


def test_score_submission_end_to_end(engine, seeded) -> None:
    with Session(engine) as s:
        quiz = service.get_published_quiz(s, seeded)
        assert quiz is not None

        perfect = service.score_submission(s, quiz, _all_yes_answers(s))
        assert perfect.overall == 100
        assert perfect.tier_name == "Hoch"  # 50–100 band
        assert set(perfect.dimension_scores) == {"alpha", "beta"}

        empty = service.score_submission(s, quiz, {})
        assert empty.overall == 0
        assert empty.tier_name == "Niedrig"  # 0–49 band
