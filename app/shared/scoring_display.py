"""app.shared.scoring_display — map any 0–100 score to a traffic-light level.

Cross-cutting presentation helper (no domain logic): turns a score into a
semantic readiness level used to colour the result page and both emails
(red / orange / green). Decoupled from quiz tiers — applies uniformly to the
overall score *and* each dimension score, so a green overall can still surface
a single red dimension. Thresholds come from `Settings` so they can be tuned
without a code change.
"""

from __future__ import annotations

from app.core.config import get_settings

# Ordered worst → best; the value is the stable code used in CSS class names
# (`ar-score--low|mid|high`) and is therefore part of the template contract.
LEVELS = ("low", "mid", "high")

# Hard hex values mirroring the `--ar-score-*` CSS tokens. Duplicated on purpose:
# HTML emails can't read CSS custom properties, so the email templates need the
# raw colours here. Keep in sync with static/brand/tokens.css.
LEVEL_COLORS = {
    "low": "#D1493B",
    "mid": "#E8A13C",
    "high": "#4F9D69",
}
LEVEL_COLORS_SOFT = {
    "low": "#F7E4E1",
    "mid": "#FBEDD6",
    "high": "#E2F0E7",
}


def level_for(score: int, *, mid: int, high: int) -> str:
    """Pure mapping: ``score < mid`` → low, ``< high`` → mid, else high."""
    if score < mid:
        return "low"
    if score < high:
        return "mid"
    return "high"


def score_level(score: int) -> str:
    """Resolve the readiness level for `score` using configured thresholds."""
    settings = get_settings()
    return level_for(
        score,
        mid=settings.score_threshold_mid,
        high=settings.score_threshold_high,
    )


def level_color(score: int, *, soft: bool = False) -> str:
    """Resolve the traffic-light hex for `score` (for inline-styled emails)."""
    table = LEVEL_COLORS_SOFT if soft else LEVEL_COLORS
    return table[score_level(score)]
