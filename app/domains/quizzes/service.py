"""Quizzes domain — read/query logic for the public player + landing.

The interface layer calls these and receives DTOs (schemas), never ORM models.
Admin write logic is added in Phase 6.
"""

from __future__ import annotations

import json

from sqlmodel import Session, col, select

from app.domains.quizzes import scoring
from app.domains.quizzes.models import (
    AnswerOption,
    Dimension,
    Question,
    Quiz,
    QuizLandingConfig,
    QuizResultConfig,
    ResultTier,
)
from app.domains.quizzes.schemas import (
    BenefitPublic,
    DimensionPublic,
    DimensionScoreView,
    EmailConfig,
    LandingView,
    OptionPublic,
    QuestionPublic,
    QuizPublic,
    ResultView,
    ScoreResult,
)
from app.shared.i18n import pick


def get_published_quiz(session: Session, slug: str) -> Quiz | None:
    quiz = session.exec(select(Quiz).where(Quiz.slug == slug)).first()
    return quiz if quiz is not None and quiz.is_published else None


def get_quiz_by_slug(session: Session, slug: str) -> Quiz | None:
    """Any quiz by slug regardless of publish state (results stay reachable)."""
    return session.exec(select(Quiz).where(Quiz.slug == slug)).first()


def get_first_published_quiz(session: Session) -> Quiz | None:
    quizzes = session.exec(select(Quiz).order_by(col(Quiz.id))).all()
    return next((q for q in quizzes if q.is_published), None)


def build_player_payload(session: Session, quiz: Quiz) -> QuizPublic:
    """Assemble the player JSON: dimensions + ordered questions + options.

    Weights are intentionally excluded — only labels reach the client.
    """
    dims = session.exec(
        select(Dimension).where(Dimension.quiz_id == quiz.id).order_by(col(Dimension.position))
    ).all()
    dim_key_by_id = {d.id: d.key for d in dims}

    questions = session.exec(
        select(Question).where(Question.quiz_id == quiz.id).order_by(col(Question.position))
    ).all()

    question_payloads: list[QuestionPublic] = []
    for q in questions:
        options = session.exec(
            select(AnswerOption)
            .where(AnswerOption.question_id == q.id)
            .order_by(col(AnswerOption.position))
        ).all()
        question_payloads.append(
            QuestionPublic(
                id=q.id or 0,
                dimension_key=dim_key_by_id.get(q.dimension_id, ""),
                text_de=q.text_de,
                text_en=q.text_en,
                help_de=q.help_de,
                help_en=q.help_en,
                options=[
                    OptionPublic(id=o.id or 0, label_de=o.label_de, label_en=o.label_en)
                    for o in options
                ],
            )
        )

    return QuizPublic(
        slug=quiz.slug,
        title_de=quiz.title_de,
        title_en=quiz.title_en,
        default_lang=quiz.default_lang,
        estimated_minutes=quiz.estimated_minutes,
        dimensions=[DimensionPublic(key=d.key, name_de=d.name_de, name_en=d.name_en) for d in dims],
        questions=question_payloads,
    )


def get_landing_view(session: Session, quiz: Quiz) -> LandingView:
    """Resolve the landing content for `quiz`, falling back to the quiz title."""
    cfg = session.exec(
        select(QuizLandingConfig).where(QuizLandingConfig.quiz_id == quiz.id)
    ).first()

    benefits: list[BenefitPublic] = []
    if cfg and cfg.benefits_json:
        try:
            benefits = [BenefitPublic(**b) for b in json.loads(cfg.benefits_json)]
        except (ValueError, TypeError):
            benefits = []

    return LandingView(
        slug=quiz.slug,
        default_lang=quiz.default_lang,
        estimated_minutes=quiz.estimated_minutes,
        hero_eyebrow_de=cfg.hero_eyebrow_de if cfg else "",
        hero_eyebrow_en=cfg.hero_eyebrow_en if cfg else "",
        hero_headline_de=(cfg.hero_headline_de if cfg else "") or quiz.title_de,
        hero_headline_en=(cfg.hero_headline_en if cfg else "") or quiz.title_en,
        hero_subline_de=cfg.hero_subline_de if cfg else "",
        hero_subline_en=cfg.hero_subline_en if cfg else "",
        cta_label_de=(cfg.cta_label_de if cfg else "") or "Scorecard starten →",
        cta_label_en=(cfg.cta_label_en if cfg else "") or "Take the scorecard →",
        benefits=benefits,
    )


def score_submission(session: Session, quiz: Quiz, answers: dict[int, int]) -> ScoreResult:
    """Compute the per-dimension + overall score and resolve the tier.

    `answers` maps question_id -> chosen option_id. Unknown / mismatched ids are
    ignored defensively. The heavy lifting is delegated to the pure `scoring`
    functions; this function only gathers the weights from the DB.
    """
    questions = session.exec(select(Question).where(Question.quiz_id == quiz.id)).all()
    question_by_id = {q.id: q for q in questions}

    dims = session.exec(
        select(Dimension).where(Dimension.quiz_id == quiz.id).order_by(col(Dimension.position))
    ).all()
    dim_key_by_id = {d.id: d.key for d in dims}
    dim_weights = {d.key: d.weight for d in dims}

    grouped: dict[str, list[float]] = {d.key: [] for d in dims}
    for question_id, option_id in answers.items():
        question = question_by_id.get(question_id)
        if question is None:
            continue
        option = session.get(AnswerOption, option_id)
        if option is None or option.question_id != question_id:
            continue
        key = dim_key_by_id.get(question.dimension_id)
        if key is not None:
            grouped[key].append(option.weight)

    dimension_scores = {
        key: scoring.dimension_score(weights) for key, weights in grouped.items() if weights
    }
    overall = scoring.overall_score(dimension_scores, dim_weights)

    tiers = session.exec(
        select(ResultTier).where(ResultTier.quiz_id == quiz.id).order_by(col(ResultTier.position))
    ).all()
    tier_tuples = [(t.id, t.min_score, t.max_score) for t in tiers if t.id is not None]
    tier_id = scoring.resolve_tier(overall, tier_tuples)
    tier_name = next((t.name_de for t in tiers if t.id == tier_id), None)

    return ScoreResult(
        overall=overall,
        dimension_scores=dimension_scores,
        tier_id=tier_id,
        tier_name=tier_name,
    )


def get_result_view(
    session: Session,
    slug: str,
    tier_id: int | None,
    dimension_scores: dict[str, int],
    lang: str,
) -> ResultView:
    """Build the localized results-page content from the persisted scores."""
    quiz = get_quiz_by_slug(session, slug)
    cfg = (
        session.exec(select(QuizResultConfig).where(QuizResultConfig.quiz_id == quiz.id)).first()
        if quiz is not None
        else None
    )
    tier = session.get(ResultTier, tier_id) if tier_id is not None else None

    dims = (
        session.exec(
            select(Dimension).where(Dimension.quiz_id == quiz.id).order_by(col(Dimension.position))
        ).all()
        if quiz is not None
        else []
    )
    dimension_views = [
        DimensionScoreView(
            name=pick(d.name_de, d.name_en, lang),
            score=dimension_scores.get(d.key, 0),
        )
        for d in dims
    ]

    return ResultView(
        intro=pick(cfg.intro_de, cfg.intro_en, lang) if cfg else "",
        show_breakdown=cfg.show_dimension_breakdown if cfg else True,
        tier_name=pick(tier.name_de, tier.name_en, lang) if tier else "",
        tier_headline=pick(tier.headline_de, tier.headline_en, lang) if tier else "",
        tier_body=pick(tier.body_de, tier.body_en, lang) if tier else "",
        cta_label=pick(tier.cta_label_de, tier.cta_label_en, lang) if tier else None,
        cta_url=tier.cta_url if tier else None,
        dimensions=dimension_views,
    )


def get_result_email_config(session: Session, quiz: Quiz, lang: str) -> EmailConfig:
    """Resolve the result-email subject/body/recipients for `quiz` in `lang`."""
    cfg = session.exec(select(QuizResultConfig).where(QuizResultConfig.quiz_id == quiz.id)).first()
    if cfg is None:
        return EmailConfig(subject_template="", body_template="", notify_emails="")
    return EmailConfig(
        subject_template=pick(cfg.email_subject_de, cfg.email_subject_en, lang),
        body_template=pick(cfg.email_body_de, cfg.email_body_en, lang),
        notify_emails=cfg.notify_emails,
    )
