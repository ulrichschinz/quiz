"""Unit tests for the traffic-light score-level helper."""

from __future__ import annotations

from app.shared.scoring_display import level_for, score_level


def test_level_for_buckets_by_thresholds() -> None:
    # score < mid → low, < high → mid, else high (boundaries are inclusive at the top)
    assert level_for(0, mid=40, high=70) == "low"
    assert level_for(39, mid=40, high=70) == "low"
    assert level_for(40, mid=40, high=70) == "mid"
    assert level_for(69, mid=40, high=70) == "mid"
    assert level_for(70, mid=40, high=70) == "high"
    assert level_for(100, mid=40, high=70) == "high"


def test_score_level_uses_configured_thresholds(monkeypatch) -> None:
    monkeypatch.setenv("SCORE_THRESHOLD_MID", "50")
    monkeypatch.setenv("SCORE_THRESHOLD_HIGH", "80")
    assert score_level(49) == "low"
    assert score_level(50) == "mid"
    assert score_level(79) == "mid"
    assert score_level(80) == "high"


def test_score_level_defaults(monkeypatch) -> None:
    monkeypatch.delenv("SCORE_THRESHOLD_MID", raising=False)
    monkeypatch.delenv("SCORE_THRESHOLD_HIGH", raising=False)
    assert score_level(30) == "low"
    assert score_level(55) == "mid"
    assert score_level(90) == "high"
