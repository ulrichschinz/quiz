"""Unit tests for the domain models (in-memory SQLite, no HTTP)."""

from __future__ import annotations

import json

from sqlmodel import Session, select

from app.domains.quizzes.models import AnswerOption, Dimension, Question, Quiz
from app.domains.submissions.models import Submission


def test_quiz_question_tree_roundtrip(engine) -> None:
    with Session(engine) as s:
        quiz = Quiz(slug="t", title_de="T", title_en="T")
        s.add(quiz)
        s.commit()
        s.refresh(quiz)

        dim = Dimension(quiz_id=quiz.id, key="strategy", name_de="S", name_en="S")
        s.add(dim)
        s.commit()
        s.refresh(dim)

        q = Question(quiz_id=quiz.id, dimension_id=dim.id, text_de="?", text_en="?")
        s.add(q)
        s.commit()
        s.refresh(q)
        s.add(AnswerOption(question_id=q.id, label_de="a", label_en="a", weight=1.0))
        s.commit()

        options = s.exec(select(AnswerOption).where(AnswerOption.question_id == q.id)).all()

    assert len(options) == 1
    assert options[0].weight == 1.0


def test_submission_persists_scores_as_json(engine) -> None:
    with Session(engine) as s:
        sub = Submission(
            public_id="abc123",
            quiz_id=1,
            quiz_slug="t",
            overall_score=72,
            dimension_scores_json=json.dumps({"strategy": 80, "leadership": 64}),
            tier_name="Leader",
            email="lead@example.com",
        )
        s.add(sub)
        s.commit()
        loaded = s.exec(select(Submission).where(Submission.public_id == "abc123")).one()

    assert loaded.overall_score == 72
    assert json.loads(loaded.dimension_scores_json)["strategy"] == 80
    assert loaded.crm_pushed is False
