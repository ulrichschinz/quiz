"""Unit tests for the quizzes read service (payload assembly, no weight leak)."""

from __future__ import annotations

from sqlmodel import Session

from app.domains.quizzes import service


def test_player_payload_has_questions_and_no_weights(engine, seeded) -> None:
    with Session(engine) as s:
        quiz = service.get_published_quiz(s, seeded)
        assert quiz is not None
        payload = service.build_player_payload(s, quiz)

    assert len(payload.questions) == 2
    assert {d.key for d in payload.dimensions} == {"alpha", "beta"}
    # Weights must never reach the client.
    assert "weight" not in str(payload.model_dump())
    assert all(len(q.options) == 2 for q in payload.questions)


def test_unpublished_quiz_is_not_served(engine, seeded) -> None:
    with Session(engine) as s:
        quiz = service.get_published_quiz(s, seeded)
        assert quiz is not None
        quiz.is_published = False
        s.add(quiz)
        s.commit()
        assert service.get_published_quiz(s, seeded) is None


def test_result_email_body_follows_language(engine, seeded) -> None:
    """An English quiz must resolve the English body, German the German one."""
    with Session(engine) as s:
        quiz = service.get_published_quiz(s, seeded)
        assert quiz is not None
        de = service.get_result_email_config(s, quiz, "de")
        en = service.get_result_email_config(s, quiz, "en")

    assert de.body_template.startswith("Hallo")
    assert en.body_template.startswith("Hi")


def test_new_quiz_ships_with_default_email_copy(engine) -> None:
    """A freshly created quiz is pre-filled with good German + English copy."""
    from app.domains.quizzes import admin

    with Session(engine) as s:
        quiz = admin.create_quiz(s, slug="fresh", title_de="Frisch", title_en="Fresh")
        assert quiz.id is not None
        cfg = admin.get_result_config(s, quiz.id)

    assert cfg is not None
    assert "Agentic Reach" in cfg.email_subject_de
    assert cfg.email_body_de and cfg.email_body_en
    assert "{score}" in cfg.email_body_en


def test_result_view_cta_defaults_to_booking_link(engine, seeded) -> None:
    """With no per-tier CTA, the result CTA points at the landing contact anchor."""
    with Session(engine) as s:
        de = service.get_result_view(s, seeded, None, {}, "de")
        en = service.get_result_view(s, seeded, None, {}, "en")

    assert de.cta_url == "https://agentic-reach.com/?lang=de"
    assert en.cta_url == "https://agentic-reach.com/?lang=en"
    assert "Gespräch" in de.cta_label and "call" in en.cta_label.lower()


def test_answer_breakdown_groups_answers_by_dimension(engine, seeded) -> None:
    from sqlmodel import select

    from app.domains.quizzes.models import AnswerOption, Question

    with Session(engine) as s:
        quiz = service.get_published_quiz(s, seeded)
        assert quiz is not None
        answers: dict[int, int] = {}
        for q in s.exec(select(Question)).all():
            best = s.exec(
                select(AnswerOption).where(
                    AnswerOption.question_id == q.id, AnswerOption.weight == 1.0
                )
            ).first()
            assert q.id is not None and best is not None and best.id is not None
            answers[q.id] = best.id
        scored = service.score_submission(s, quiz, answers)
        breakdown = service.get_answer_breakdown(s, quiz, answers, scored.dimension_scores, "de")

    assert {d.name for d in breakdown}  # dimensions present
    all_qs = [qa for d in breakdown for qa in d.questions]
    # Every question is answered, and best (weight 1.0) answers earn full credit.
    assert all_qs and all(qa.answered and qa.value == 100 for qa in all_qs)


def test_answer_breakdown_marks_unanswered(engine, seeded) -> None:
    with Session(engine) as s:
        quiz = service.get_published_quiz(s, seeded)
        assert quiz is not None
        breakdown = service.get_answer_breakdown(s, quiz, {}, {}, "de")

    qs = [qa for d in breakdown for qa in d.questions]
    assert qs and all(not qa.answered and qa.value == 0 for qa in qs)


def test_landing_view_falls_back_to_title(engine) -> None:
    from app.domains.quizzes.models import Quiz

    with Session(engine) as s:
        quiz = Quiz(slug="bare", title_de="Nackt", title_en="Bare", is_published=True)
        s.add(quiz)
        s.commit()
        s.refresh(quiz)
        view = service.get_landing_view(s, quiz)

    assert view.hero_headline_de == "Nackt"
    assert view.cta_label_de  # non-empty default
