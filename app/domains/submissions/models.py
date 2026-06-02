"""Submissions domain — SQLModel tables.

`Submission` is the lead. Scores are computed and persisted at submit time, so
the results page and the CRM payload stay deterministic even if the quiz config
is edited later. The reference to the quiz is a soft `quiz_id` (no SQL FK) plus
copied `quiz_slug` and `tier_name` — keeping the two domains decoupled at the
DB level too (enables a later DB split without a data migration).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from app.core.db import SQLModel
from app.shared.clock import utcnow


class Submission(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)  # uuid4 hex → /r/<public_id>

    # Soft reference to the quiz (no cross-domain FK; copies for resilience).
    quiz_id: int = Field(index=True)
    quiz_slug: str = ""
    lang: str = Field(default="de")

    # Answers + computed, persisted scores.
    answers_json: str = "{}"  # {question_id: option_id}
    overall_score: int = Field(default=0)  # 0–100
    dimension_scores_json: str = "{}"  # {dimension_key: score}
    tier_id: int | None = Field(default=None)
    tier_name: str | None = Field(default=None)  # copied for export resilience

    # Captured lead (email gate at the results step).
    email: str | None = Field(default=None, index=True)
    name: str | None = Field(default=None)
    company: str | None = Field(default=None)
    consent: bool = Field(default=False)  # DSGVO marketing consent

    completed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)

    # Pipeline audit trail (one flag/error per destination).
    crm_pushed: bool = Field(default=False)
    crm_pushed_at: datetime | None = Field(default=None)
    crm_error: str | None = Field(default=None)
    email_sent: bool = Field(default=False)
    email_error: str | None = Field(default=None)
