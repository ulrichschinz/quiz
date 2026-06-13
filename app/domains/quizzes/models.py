"""Quizzes domain — SQLModel tables.

Generic, multi-quiz shape so the flagship "Agentic AI Readiness" scorecard and
any future quiz share one model:

    Quiz 1─* Dimension 1─* Question 1─* AnswerOption
    Quiz 1─* ResultTier
    Quiz 1─1 QuizLandingConfig / QuizResultConfig

All user-facing text comes in `_de`/`_en` pairs (resolved by app.shared.i18n).
Ordering uses `position` (avoids the SQL reserved word `order`). Foreign keys
stay inside this domain; `submissions` references a quiz only by a soft id +
copied scores (domain independence).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from app.core.db import SQLModel
from app.shared.clock import utcnow


class Quiz(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title_de: str = ""
    title_en: str = ""
    is_published: bool = Field(default=False)
    default_lang: str = Field(default="de")
    estimated_minutes: int = Field(default=3)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Dimension(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    quiz_id: int = Field(foreign_key="quiz.id", index=True)
    key: str = Field(index=True)  # stable code, e.g. "strategy_vision"
    name_de: str = ""
    name_en: str = ""
    # Roll-up share of the overall score, stored as a percent (all dimensions of
    # a quiz sum to ~100). The admin keeps the sum at 100; `scoring.overall_score`
    # normalises by the sum defensively, so any positive scale still works.
    weight: float = Field(default=1.0)
    position: int = Field(default=0)


class Question(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    quiz_id: int = Field(foreign_key="quiz.id", index=True)
    dimension_id: int = Field(foreign_key="dimension.id", index=True)
    text_de: str = ""
    text_en: str = ""
    help_de: str | None = Field(default=None)
    help_en: str | None = Field(default=None)
    kind: str = Field(default="single")  # "single" | "scale" (single = MVP)
    position: int = Field(default=0)
    is_required: bool = Field(default=True)


class AnswerOption(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="question.id", index=True)
    label_de: str = ""
    label_en: str = ""
    # `score_rank` (0 = best answer) is the source of truth for an option's
    # value; `weight` (fraction 0.0–1.0 of the question's max) is *derived* from
    # the rank via `scoring.weight_for_rank` and recomputed on every edit. Ranks
    # are unique + gap-free within a question, so duplicate/missing-max weights
    # are structurally impossible. `position` stays the player display order.
    score_rank: int = Field(default=0)
    weight: float = Field(default=0.0)
    position: int = Field(default=0)


class ResultTier(SQLModel, table=True):
    """A score band with its evaluation copy ("Auswertung")."""

    id: int | None = Field(default=None, primary_key=True)
    quiz_id: int = Field(foreign_key="quiz.id", index=True)
    name_de: str = ""
    name_en: str = ""
    min_score: int = Field(default=0)  # inclusive, 0–100
    max_score: int = Field(default=100)  # inclusive, 0–100
    headline_de: str = ""
    headline_en: str = ""
    body_de: str = ""
    body_en: str = ""
    cta_label_de: str | None = Field(default=None)
    cta_label_en: str | None = Field(default=None)
    cta_url: str | None = Field(default=None)
    position: int = Field(default=0)


class QuizLandingConfig(SQLModel, table=True):
    """1:1 with Quiz — the configurable landing-page content."""

    id: int | None = Field(default=None, primary_key=True)
    quiz_id: int = Field(foreign_key="quiz.id", unique=True, index=True)
    hero_eyebrow_de: str = ""
    hero_eyebrow_en: str = ""
    hero_headline_de: str = ""
    hero_headline_en: str = ""
    hero_subline_de: str = ""
    hero_subline_en: str = ""
    cta_label_de: str = ""
    cta_label_en: str = ""
    benefits_json: str = "[]"  # JSON list of {de, en} bullet points


class QuizResultConfig(SQLModel, table=True):
    """1:1 with Quiz — the configurable results page + email behaviour."""

    id: int | None = Field(default=None, primary_key=True)
    quiz_id: int = Field(foreign_key="quiz.id", unique=True, index=True)
    intro_de: str = ""
    intro_en: str = ""
    show_dimension_breakdown: bool = Field(default=True)
    email_subject_de: str = ""
    email_subject_en: str = ""
    email_body_template: str = ""  # supports {name} {score} {tier} {url}
    notify_emails: str = ""  # comma-separated team recipients
