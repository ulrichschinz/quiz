"""Unit tests for the quizzes admin CRUD (build, clone, delete)."""

from __future__ import annotations

from sqlmodel import Session

from app.domains.quizzes import admin, service


def test_build_quiz_then_score(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d1", "D1", "D1", 1.0)
        dim = admin.get_dimensions(s, quiz.id)[0]
        admin.add_question(s, quiz.id, dim.id, "Frage", "Q")
        q = admin.get_questions(s, quiz.id)[0]
        admin.add_option(s, q.id, "Nein", "No", 0.0)
        admin.add_option(s, q.id, "Ja", "Yes", 1.0)
        admin.add_tier(s, quiz.id, "Low", "Low", 0, 49)
        admin.add_tier(s, quiz.id, "High", "High", 50, 100)

        yes = next(o for o in admin.get_options(s, q.id) if o.weight == 1.0)
        result = service.score_submission(s, quiz, {q.id: yes.id})

    assert result.overall == 100
    assert result.tier_name == "High"


def test_clone_duplicates_tree_unpublished(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D", 1.0)
        clone = admin.clone_quiz(s, quiz.id)

        assert clone is not None
        assert clone.slug == "x-copy"
        assert clone.is_published is False
        assert len(admin.get_dimensions(s, clone.id)) == 1


def test_delete_removes_children(engine) -> None:
    with Session(engine) as s:
        quiz = admin.create_quiz(s, "x", "X", "X")
        admin.add_dimension(s, quiz.id, "d", "D", "D", 1.0)
        qid = quiz.id
        admin.delete_quiz(s, qid)

        assert admin.get_quiz(s, qid) is None
        assert admin.get_dimensions(s, qid) == []
        assert admin.get_landing(s, qid) is None
