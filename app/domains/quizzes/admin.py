"""Quizzes domain — admin write/read operations (CRUD for the editor UI).

Kept separate from `service.py` (public read path) so the admin surface is one
clear module. The interface layer imports this, never `models` directly. All
functions take primitives + a Session and return ORM objects for the templates.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, col, select

from app.domains.quizzes.models import (
    AnswerOption,
    Dimension,
    Question,
    Quiz,
    QuizLandingConfig,
    QuizResultConfig,
    ResultTier,
)
from app.shared.clock import utcnow


def _next_position(session: Session, model: Any, **filters: int) -> int:
    rows: list[Any] = list(session.exec(select(model)).all())
    positions = [
        r.position for r in rows if all(getattr(r, key) == value for key, value in filters.items())
    ]
    return (max(positions) + 1) if positions else 0


def _delete_where(session: Session, model: Any, **eq: int) -> None:
    """Delete every row of `model` matching the equality filters (ORM-level)."""
    stmt = select(model)
    for key, value in eq.items():
        stmt = stmt.where(getattr(model, key) == value)
    for row in session.exec(stmt).all():
        session.delete(row)


# --- Quiz ------------------------------------------------------------------
def list_quizzes(session: Session) -> list[Quiz]:
    return list(session.exec(select(Quiz).order_by(col(Quiz.id))).all())


def get_quiz(session: Session, quiz_id: int) -> Quiz | None:
    return session.get(Quiz, quiz_id)


def create_quiz(session: Session, slug: str, title_de: str, title_en: str) -> Quiz:
    quiz = Quiz(slug=slug, title_de=title_de, title_en=title_en)
    session.add(quiz)
    session.commit()
    session.refresh(quiz)
    assert quiz.id is not None
    session.add(QuizLandingConfig(quiz_id=quiz.id))
    session.add(QuizResultConfig(quiz_id=quiz.id))
    session.commit()
    return quiz


def update_quiz_meta(
    session: Session,
    quiz_id: int,
    *,
    slug: str,
    title_de: str,
    title_en: str,
    default_lang: str,
    estimated_minutes: int,
) -> None:
    quiz = session.get(Quiz, quiz_id)
    if quiz is None:
        return
    quiz.slug = slug
    quiz.title_de = title_de
    quiz.title_en = title_en
    quiz.default_lang = default_lang
    quiz.estimated_minutes = estimated_minutes
    quiz.updated_at = utcnow()
    session.add(quiz)
    session.commit()


def toggle_publish(session: Session, quiz_id: int) -> None:
    quiz = session.get(Quiz, quiz_id)
    if quiz is None:
        return
    quiz.is_published = not quiz.is_published
    quiz.updated_at = utcnow()
    session.add(quiz)
    session.commit()


def delete_quiz(session: Session, quiz_id: int) -> None:
    question_ids = [
        q.id for q in session.exec(select(Question).where(Question.quiz_id == quiz_id)).all()
    ]
    for qid in question_ids:
        if qid is not None:
            _delete_where(session, AnswerOption, question_id=qid)
    _delete_where(session, Question, quiz_id=quiz_id)
    _delete_where(session, Dimension, quiz_id=quiz_id)
    _delete_where(session, ResultTier, quiz_id=quiz_id)
    _delete_where(session, QuizLandingConfig, quiz_id=quiz_id)
    _delete_where(session, QuizResultConfig, quiz_id=quiz_id)
    _delete_where(session, Quiz, id=quiz_id)
    session.commit()


def clone_quiz(session: Session, quiz_id: int) -> Quiz | None:
    src = session.get(Quiz, quiz_id)
    if src is None:
        return None
    clone = Quiz(
        slug=f"{src.slug}-copy",
        title_de=f"{src.title_de} (Kopie)",
        title_en=f"{src.title_en} (copy)",
        default_lang=src.default_lang,
        estimated_minutes=src.estimated_minutes,
        is_published=False,
    )
    session.add(clone)
    session.commit()
    session.refresh(clone)
    assert clone.id is not None

    dim_id_map: dict[int, int] = {}
    for d in session.exec(select(Dimension).where(Dimension.quiz_id == quiz_id)).all():
        nd = Dimension(
            quiz_id=clone.id,
            key=d.key,
            name_de=d.name_de,
            name_en=d.name_en,
            weight=d.weight,
            position=d.position,
        )
        session.add(nd)
        session.commit()
        session.refresh(nd)
        assert d.id is not None and nd.id is not None
        dim_id_map[d.id] = nd.id

    for q in session.exec(select(Question).where(Question.quiz_id == quiz_id)).all():
        nq = Question(
            quiz_id=clone.id,
            dimension_id=dim_id_map.get(q.dimension_id, 0),
            text_de=q.text_de,
            text_en=q.text_en,
            help_de=q.help_de,
            help_en=q.help_en,
            kind=q.kind,
            position=q.position,
            is_required=q.is_required,
        )
        session.add(nq)
        session.commit()
        session.refresh(nq)
        assert q.id is not None and nq.id is not None
        for o in session.exec(select(AnswerOption).where(AnswerOption.question_id == q.id)).all():
            session.add(
                AnswerOption(
                    question_id=nq.id,
                    label_de=o.label_de,
                    label_en=o.label_en,
                    weight=o.weight,
                    position=o.position,
                )
            )
        session.commit()

    for t in session.exec(select(ResultTier).where(ResultTier.quiz_id == quiz_id)).all():
        session.add(
            ResultTier(
                quiz_id=clone.id,
                name_de=t.name_de,
                name_en=t.name_en,
                min_score=t.min_score,
                max_score=t.max_score,
                headline_de=t.headline_de,
                headline_en=t.headline_en,
                body_de=t.body_de,
                body_en=t.body_en,
                cta_label_de=t.cta_label_de,
                cta_label_en=t.cta_label_en,
                cta_url=t.cta_url,
                position=t.position,
            )
        )
    src_landing = session.exec(
        select(QuizLandingConfig).where(QuizLandingConfig.quiz_id == quiz_id)
    ).first()
    if src_landing is not None:
        data = src_landing.model_dump(exclude={"id", "quiz_id"})
        session.add(QuizLandingConfig(quiz_id=clone.id, **data))
    src_result = session.exec(
        select(QuizResultConfig).where(QuizResultConfig.quiz_id == quiz_id)
    ).first()
    if src_result is not None:
        data = src_result.model_dump(exclude={"id", "quiz_id"})
        session.add(QuizResultConfig(quiz_id=clone.id, **data))
    session.commit()
    return clone


# --- Dimensions ------------------------------------------------------------
def get_dimensions(session: Session, quiz_id: int) -> list[Dimension]:
    return list(
        session.exec(
            select(Dimension).where(Dimension.quiz_id == quiz_id).order_by(col(Dimension.position))
        ).all()
    )


def add_dimension(
    session: Session, quiz_id: int, key: str, name_de: str, name_en: str, weight: float
) -> None:
    session.add(
        Dimension(
            quiz_id=quiz_id,
            key=key,
            name_de=name_de,
            name_en=name_en,
            weight=weight,
            position=_next_position(session, Dimension, quiz_id=quiz_id),
        )
    )
    session.commit()


def update_dimension(
    session: Session,
    dim_id: int,
    *,
    key: str,
    name_de: str,
    name_en: str,
    weight: float,
    position: int,
) -> None:
    dim = session.get(Dimension, dim_id)
    if dim is None:
        return
    dim.key, dim.name_de, dim.name_en = key, name_de, name_en
    dim.weight, dim.position = weight, position
    session.add(dim)
    session.commit()


def delete_dimension(session: Session, dim_id: int) -> None:
    dim = session.get(Dimension, dim_id)
    if dim is None:
        return
    for q in session.exec(select(Question).where(Question.dimension_id == dim_id)).all():
        if q.id is not None:
            _delete_where(session, AnswerOption, question_id=q.id)
    _delete_where(session, Question, dimension_id=dim_id)
    session.delete(dim)
    session.commit()


# --- Questions + options ---------------------------------------------------
def get_questions(session: Session, quiz_id: int) -> list[Question]:
    return list(
        session.exec(
            select(Question).where(Question.quiz_id == quiz_id).order_by(col(Question.position))
        ).all()
    )


def get_options(session: Session, question_id: int) -> list[AnswerOption]:
    return list(
        session.exec(
            select(AnswerOption)
            .where(AnswerOption.question_id == question_id)
            .order_by(col(AnswerOption.position))
        ).all()
    )


def add_question(
    session: Session, quiz_id: int, dimension_id: int, text_de: str, text_en: str
) -> None:
    session.add(
        Question(
            quiz_id=quiz_id,
            dimension_id=dimension_id,
            text_de=text_de,
            text_en=text_en,
            position=_next_position(session, Question, quiz_id=quiz_id),
        )
    )
    session.commit()


def update_question(
    session: Session,
    question_id: int,
    *,
    dimension_id: int,
    text_de: str,
    text_en: str,
    help_de: str,
    help_en: str,
    position: int,
) -> None:
    q = session.get(Question, question_id)
    if q is None:
        return
    q.dimension_id, q.text_de, q.text_en = dimension_id, text_de, text_en
    q.help_de, q.help_en, q.position = help_de or None, help_en or None, position
    session.add(q)
    session.commit()


def delete_question(session: Session, question_id: int) -> None:
    _delete_where(session, AnswerOption, question_id=question_id)
    _delete_where(session, Question, id=question_id)
    session.commit()


def add_option(
    session: Session, question_id: int, label_de: str, label_en: str, weight: float
) -> None:
    session.add(
        AnswerOption(
            question_id=question_id,
            label_de=label_de,
            label_en=label_en,
            weight=weight,
            position=_next_position(session, AnswerOption, question_id=question_id),
        )
    )
    session.commit()


def update_option(
    session: Session, option_id: int, *, label_de: str, label_en: str, weight: float, position: int
) -> None:
    o = session.get(AnswerOption, option_id)
    if o is None:
        return
    o.label_de, o.label_en, o.weight, o.position = label_de, label_en, weight, position
    session.add(o)
    session.commit()


def delete_option(session: Session, option_id: int) -> None:
    _delete_where(session, AnswerOption, id=option_id)
    session.commit()


# --- Tiers -----------------------------------------------------------------
def get_tiers(session: Session, quiz_id: int) -> list[ResultTier]:
    return list(
        session.exec(
            select(ResultTier)
            .where(ResultTier.quiz_id == quiz_id)
            .order_by(col(ResultTier.position))
        ).all()
    )


def add_tier(
    session: Session, quiz_id: int, name_de: str, name_en: str, min_score: int, max_score: int
) -> None:
    session.add(
        ResultTier(
            quiz_id=quiz_id,
            name_de=name_de,
            name_en=name_en,
            min_score=min_score,
            max_score=max_score,
            position=_next_position(session, ResultTier, quiz_id=quiz_id),
        )
    )
    session.commit()


def update_tier(
    session: Session,
    tier_id: int,
    *,
    name_de: str,
    name_en: str,
    min_score: int,
    max_score: int,
    headline_de: str,
    headline_en: str,
    body_de: str,
    body_en: str,
    cta_label_de: str,
    cta_label_en: str,
    cta_url: str,
    position: int,
) -> None:
    t = session.get(ResultTier, tier_id)
    if t is None:
        return
    t.name_de, t.name_en, t.min_score, t.max_score = name_de, name_en, min_score, max_score
    t.headline_de, t.headline_en = headline_de, headline_en
    t.body_de, t.body_en = body_de, body_en
    t.cta_label_de, t.cta_label_en = cta_label_de or None, cta_label_en or None
    t.cta_url, t.position = cta_url or None, position
    session.add(t)
    session.commit()


def delete_tier(session: Session, tier_id: int) -> None:
    _delete_where(session, ResultTier, id=tier_id)
    session.commit()


# --- Landing + result config ----------------------------------------------
def get_landing(session: Session, quiz_id: int) -> QuizLandingConfig | None:
    return session.exec(
        select(QuizLandingConfig).where(QuizLandingConfig.quiz_id == quiz_id)
    ).first()


def update_landing(
    session: Session,
    quiz_id: int,
    *,
    hero_eyebrow_de: str,
    hero_eyebrow_en: str,
    hero_headline_de: str,
    hero_headline_en: str,
    hero_subline_de: str,
    hero_subline_en: str,
    cta_label_de: str,
    cta_label_en: str,
    benefits_json: str,
) -> None:
    cfg = get_landing(session, quiz_id)
    if cfg is None:
        cfg = QuizLandingConfig(quiz_id=quiz_id)
    cfg.hero_eyebrow_de, cfg.hero_eyebrow_en = hero_eyebrow_de, hero_eyebrow_en
    cfg.hero_headline_de, cfg.hero_headline_en = hero_headline_de, hero_headline_en
    cfg.hero_subline_de, cfg.hero_subline_en = hero_subline_de, hero_subline_en
    cfg.cta_label_de, cfg.cta_label_en = cta_label_de, cta_label_en
    cfg.benefits_json = benefits_json or "[]"
    session.add(cfg)
    session.commit()


def get_result_config(session: Session, quiz_id: int) -> QuizResultConfig | None:
    return session.exec(select(QuizResultConfig).where(QuizResultConfig.quiz_id == quiz_id)).first()


def update_result_config(
    session: Session,
    quiz_id: int,
    *,
    intro_de: str,
    intro_en: str,
    show_dimension_breakdown: bool,
    email_subject_de: str,
    email_subject_en: str,
    email_body_template: str,
    notify_emails: str,
) -> None:
    cfg = get_result_config(session, quiz_id)
    if cfg is None:
        cfg = QuizResultConfig(quiz_id=quiz_id)
    cfg.intro_de, cfg.intro_en = intro_de, intro_en
    cfg.show_dimension_breakdown = show_dimension_breakdown
    cfg.email_subject_de, cfg.email_subject_en = email_subject_de, email_subject_en
    cfg.email_body_template, cfg.notify_emails = email_body_template, notify_emails
    session.add(cfg)
    session.commit()
