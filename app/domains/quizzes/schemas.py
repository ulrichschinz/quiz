"""Quizzes domain — public DTOs (no ORM, no FastAPI import).

These are what the interface layer is allowed to touch (import-linter forbids
interfaces from importing `models`). The player payload deliberately omits
answer weights — scoring stays server-side.
"""

from __future__ import annotations

from pydantic import BaseModel


class OptionPublic(BaseModel):
    id: int
    label_de: str
    label_en: str


class QuestionPublic(BaseModel):
    id: int
    dimension_key: str
    text_de: str
    text_en: str
    help_de: str | None
    help_en: str | None
    options: list[OptionPublic]


class DimensionPublic(BaseModel):
    key: str
    name_de: str
    name_en: str


class QuizPublic(BaseModel):
    """The quiz player payload — questions + options, NO weights."""

    slug: str
    title_de: str
    title_en: str
    default_lang: str
    estimated_minutes: int
    dimensions: list[DimensionPublic]
    questions: list[QuestionPublic]


class BenefitPublic(BaseModel):
    de: str
    en: str


class LandingView(BaseModel):
    """Everything the landing template renders (both languages embedded)."""

    slug: str
    default_lang: str
    estimated_minutes: int
    hero_eyebrow_de: str
    hero_eyebrow_en: str
    hero_headline_de: str
    hero_headline_en: str
    hero_subline_de: str
    hero_subline_en: str
    cta_label_de: str
    cta_label_en: str
    benefits: list[BenefitPublic]


class ScoreResult(BaseModel):
    """Output of the scoring engine — persisted onto the Submission."""

    overall: int
    dimension_scores: dict[str, int]  # dimension key -> 0–100
    tier_id: int | None
    tier_name: str | None


class DimensionScoreView(BaseModel):
    name: str
    score: int


class EmailConfig(BaseModel):
    """Result-email settings for a quiz, resolved to one language."""

    subject_template: str  # supports {score}
    body_template: str  # supports {name} {score} {tier} {url}
    notify_emails: str  # comma-separated team recipients


class ResultView(BaseModel):
    """The results page content, resolved to a single language."""

    intro: str
    show_breakdown: bool
    tier_name: str
    tier_headline: str
    tier_body: str
    cta_label: str | None
    cta_url: str | None
    dimensions: list[DimensionScoreView]
