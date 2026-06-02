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
