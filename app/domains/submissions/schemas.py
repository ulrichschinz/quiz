"""Submissions domain — DTOs (no ORM, no FastAPI import)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.shared.validation import clean_single_line, normalize_email_address

# SEC-003: hard upper bounds on the public submit payload. The per-quiz bound
# (answers == the quiz's questions) is enforced by the quizzes service.
MAX_ANSWERS = 200
MAX_TEXT_FIELD_LENGTH = 200
_MAX_ID = 2**31 - 1


class SubmitRequest(BaseModel):
    """Payload posted by the quiz player at the end of the flow.

    `email` is exactly one plain address and required — the player's lead form
    is an email gate (`<input type=email required>`), now enforced server-side
    (SEC-002/017). `name` / `company` are optional single lines.
    """

    answers: Annotated[dict[int, int], Field(max_length=MAX_ANSWERS)]  # question_id -> option_id
    email: str = Field(max_length=320)  # pre-parse bound; the validator enforces 254
    name: str | None = Field(default=None, max_length=MAX_TEXT_FIELD_LENGTH + 50)
    company: str | None = Field(default=None, max_length=MAX_TEXT_FIELD_LENGTH + 50)
    consent: bool = False
    lang: str = Field(default="de", max_length=8)

    @field_validator("answers")
    @classmethod
    def _ids_in_range(cls, v: dict[int, int]) -> dict[int, int]:
        for question_id, option_id in v.items():
            if not (0 < question_id <= _MAX_ID and 0 < option_id <= _MAX_ID):
                raise ValueError("answer ids out of range")
        return v

    @field_validator("email")
    @classmethod
    def _single_address(cls, v: str) -> str:
        return normalize_email_address(v)

    @field_validator("name", "company")
    @classmethod
    def _single_line(cls, v: str | None) -> str | None:
        return clean_single_line(v, max_length=MAX_TEXT_FIELD_LENGTH)


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
