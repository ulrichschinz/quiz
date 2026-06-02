"""Submissions domain — DTOs (no ORM, no FastAPI import)."""

from __future__ import annotations

from pydantic import BaseModel


class SubmitRequest(BaseModel):
    """Payload posted by the quiz player at the end of the flow."""

    answers: dict[int, int]  # question_id -> option_id
    email: str
    name: str | None = None
    company: str | None = None
    consent: bool = False
    lang: str = "de"


class SubmissionView(BaseModel):
    """What the results page needs from a stored submission."""

    public_id: str
    quiz_slug: str
    lang: str
    overall_score: int
    dimension_scores: dict[str, int]
    tier_id: int | None
    tier_name: str | None
    name: str | None
    email: str | None
    company: str | None
