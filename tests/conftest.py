"""Shared test fixtures.

Each test gets an isolated in-memory SQLite engine wired into the app's
`get_session` dependency, so tests never touch the on-disk quiz.db and run in
any order without shared state.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import app.tables  # noqa: F401  registers every domain table on the metadata
from app.core import db as core_db
from app.main import app


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine, monkeypatch) -> Iterator[TestClient]:
    """A TestClient whose get_session yields the in-memory engine's session."""

    def _get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[core_db.get_session] = _get_session
    # Skip on-disk schema creation in the lifespan — the fixture owns the schema.
    monkeypatch.setattr(core_db, "create_db", lambda: None)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(engine) -> str:
    """Insert a minimal published quiz (2 dimensions, weighted options, 2 tiers,
    landing + result config) into the test engine. Returns the quiz slug."""
    from app.domains.quizzes.models import (
        AnswerOption,
        Dimension,
        Question,
        Quiz,
        QuizLandingConfig,
        QuizResultConfig,
        ResultTier,
    )

    with Session(engine) as s:
        quiz = Quiz(slug="test-quiz", title_de="Test", title_en="Test", is_published=True)
        s.add(quiz)
        s.commit()
        s.refresh(quiz)

        for i, key in enumerate(["alpha", "beta"]):
            d = Dimension(
                quiz_id=quiz.id, key=key, name_de=key.upper(), name_en=key, weight=50.0, position=i
            )
            s.add(d)
            s.commit()
            s.refresh(d)
            q = Question(quiz_id=quiz.id, dimension_id=d.id, text_de="Frage", text_en="Q", position=0)
            s.add(q)
            s.commit()
            s.refresh(q)
            # score_rank 0 = best ("Ja", weight 1.0); rank 1 = worst ("Nein", weight 0.0).
            s.add(AnswerOption(question_id=q.id, label_de="Ja", label_en="Yes", score_rank=0, weight=1.0, position=1))
            s.add(AnswerOption(question_id=q.id, label_de="Nein", label_en="No", score_rank=1, weight=0.0, position=0))
            s.commit()

        s.add(ResultTier(quiz_id=quiz.id, name_de="Niedrig", name_en="Low", min_score=0, max_score=49, headline_de="lo", headline_en="lo", position=0))
        s.add(ResultTier(quiz_id=quiz.id, name_de="Hoch", name_en="High", min_score=50, max_score=100, headline_de="hi", headline_en="hi", position=1))
        s.add(
            QuizLandingConfig(
                quiz_id=quiz.id,
                hero_headline_de="Bereit?",
                hero_headline_en="Ready?",
                cta_label_de="Start DE",
                cta_label_en="Start EN",
                benefits_json='[{"de":"Vorteil","en":"Benefit"}]',
            )
        )
        s.add(
            QuizResultConfig(
                quiz_id=quiz.id,
                intro_de="Ergebnis",
                intro_en="Result",
                email_subject_de="Score {score}",
                email_subject_en="Score {score}",
                email_body_de="Hallo {name}, {score}/100 ({tier}) {url}",
                email_body_en="Hi {name}, {score}/100 ({tier}) {url}",
                notify_emails="team@example.com",
            )
        )
        s.commit()
    return "test-quiz"
