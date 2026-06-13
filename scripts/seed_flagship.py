#!/usr/bin/env python3
"""Seed the flagship "Agentic AI Readiness" scorecard.

Idempotent: skips if a quiz with the slug already exists. Run via `make seed`
(or `python scripts/seed_flagship.py`). Creates the four readiness dimensions,
their questions + weighted options, three result tiers, and the landing/result
copy — everything an admin can later edit through the UI.
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from app.core.db import create_db, engine
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

SLUG = "agentic-ai-readiness"

# Likert options shared by every question, best → worst. The order IS the
# ranking: `score_rank` is the index, `weight` is derived from it.
SCALE = [
    {"de": "Trifft voll zu", "en": "Fully"},
    {"de": "Eher schon", "en": "Somewhat yes"},
    {"de": "Eher nicht", "en": "Somewhat not"},
    {"de": "Trifft nicht zu", "en": "Not at all"},
]

# (key, name_de, name_en, [ (text_de, text_en), ... ])
DIMENSIONS = [
    (
        "strategy_vision",
        "Strategie & Vision",
        "Strategy & Vision",
        [
            (
                "Wir haben einen konkreten Plan für den Einsatz von KI-Agenten.",
                "We have a concrete plan for deploying AI agents.",
            ),
            (
                "Unsere KI-Initiativen sind an klaren Geschäftszielen ausgerichtet.",
                "Our AI initiatives are aligned to clear business goals.",
            ),
        ],
    ),
    (
        "leadership_alignment",
        "Führungs-Alignment",
        "Leadership Alignment",
        [
            (
                "Die Führung steht aktiv und sichtbar hinter dem Thema KI.",
                "Leadership actively and visibly backs the AI agenda.",
            ),
            (
                "Es gibt klare Verantwortlichkeiten für KI-Vorhaben.",
                "There is clear ownership for AI initiatives.",
            ),
        ],
    ),
    (
        "governance_operating_model",
        "Governance & Betriebsmodell",
        "Governance & Operating Model",
        [
            (
                "Unsere Prozesse sind auf den Einsatz von KI-Agenten vorbereitet.",
                "Our processes are ready for AI agents to operate in.",
            ),
            (
                "Wir haben Leitplanken für einen sicheren, verantwortungsvollen KI-Einsatz.",
                "We have guardrails for safe, responsible AI use.",
            ),
        ],
    ),
    (
        "workforce_change_readiness",
        "Belegschaft & Veränderungsbereitschaft",
        "Workforce & Change Readiness",
        [
            (
                "Unsere Teams haben die Fähigkeiten, mit KI-Agenten zu arbeiten.",
                "Our teams have the skills to work with AI agents.",
            ),
            (
                "Die Organisation kann sich schnell an neue KI-Arbeitsweisen anpassen.",
                "The organization can adapt quickly to new AI ways of working.",
            ),
        ],
    ),
]

TIERS = [
    {
        "name_de": "Explorer",
        "name_en": "Explorer",
        "min_score": 0,
        "max_score": 39,
        "headline_de": "Sie stehen am Anfang der agentischen Reise.",
        "headline_en": "You're at the start of the agentic journey.",
        "body_de": (
            "Das Bewusstsein ist da, aber es fehlt ein systematischer Plan. Jetzt "
            "zählt: ein klarer erster Use Case, Rückhalt der Führung und erste "
            "Leitplanken."
        ),
        "body_en": (
            "Awareness is there, but a systematic plan is missing. What counts now: "
            "one clear first use case, leadership backing and first guardrails."
        ),
    },
    {
        "name_de": "Builder",
        "name_en": "Builder",
        "min_score": 40,
        "max_score": 69,
        "headline_de": "Sie sind auf dem Weg — mit Lücken.",
        "headline_en": "You're on your way — with gaps.",
        "body_de": (
            "Fundament und erste Initiativen stehen. Der Hebel liegt darin, "
            "Governance und Skills nachzuziehen, damit KI-Agenten verlässlich "
            "skalieren."
        ),
        "body_en": (
            "Foundations and first initiatives are in place. The lever now is "
            "catching up on governance and skills so AI agents scale reliably."
        ),
    },
    {
        "name_de": "Leader",
        "name_en": "Leader",
        "min_score": 70,
        "max_score": 100,
        "headline_de": "Sie gehören zu den Vorreitern.",
        "headline_en": "You're among the front-runners.",
        "body_de": (
            "Strategie, Führung, Governance und Belegschaft greifen ineinander. "
            "Jetzt geht es um Tempo: agentische Use Cases breit ausrollen und den "
            "Vorsprung halten."
        ),
        "body_en": (
            "Strategy, leadership, governance and workforce align. Now it's about "
            "speed: roll out agentic use cases broadly and keep your edge."
        ),
    },
]


def _seed(session: Session) -> None:
    quiz = Quiz(
        slug=SLUG,
        title_de="Agentic AI Readiness",
        title_en="Agentic AI Readiness",
        is_published=True,
        default_lang="de",
        estimated_minutes=3,
    )
    session.add(quiz)
    session.commit()
    session.refresh(quiz)
    assert quiz.id is not None

    for d_pos, (key, name_de, name_en, questions) in enumerate(DIMENSIONS):
        dim = Dimension(
            quiz_id=quiz.id,
            key=key,
            name_de=name_de,
            name_en=name_en,
            weight=round(100 / len(DIMENSIONS), 1),  # equal percent share by default
            position=d_pos,
        )
        session.add(dim)
        session.commit()
        session.refresh(dim)
        assert dim.id is not None

        for q_pos, (text_de, text_en) in enumerate(questions):
            question = Question(
                quiz_id=quiz.id,
                dimension_id=dim.id,
                text_de=text_de,
                text_en=text_en,
                position=q_pos,
            )
            session.add(question)
            session.commit()
            session.refresh(question)
            assert question.id is not None

            for rank, labels in enumerate(SCALE):
                session.add(
                    AnswerOption(
                        question_id=question.id,
                        label_de=labels["de"],
                        label_en=labels["en"],
                        score_rank=rank,
                        weight=scoring.weight_for_rank(rank, len(SCALE)),
                        position=rank,
                    )
                )
            session.commit()

    for t_pos, tier in enumerate(TIERS):
        session.add(
            ResultTier(
                quiz_id=quiz.id,
                position=t_pos,
                cta_label_de="Gespräch vereinbaren →",
                cta_label_en="Book a call →",
                cta_url="https://agentic-reach.com/kontakt",
                **tier,
            )
        )
    session.commit()

    session.add(
        QuizLandingConfig(
            quiz_id=quiz.id,
            hero_eyebrow_de="// Agentic AI Readiness",
            hero_eyebrow_en="// Agentic AI Readiness",
            hero_headline_de="Ist Ihre Organisation bereit für das <em>agentische</em> KI-Zeitalter?",
            hero_headline_en="Is your organization ready for the <em>agentic</em> AI era?",
            hero_subline_de=(
                "In 3 Minuten herausfinden — kostenlos, ohne Verpflichtung, mit "
                "konkreten nächsten Schritten."
            ),
            hero_subline_en=(
                "Find out in 3 minutes — free, no strings attached, with actionable next steps."
            ),
            cta_label_de="Scorecard starten →",
            cta_label_en="Take the scorecard →",
            benefits_json=json.dumps(
                [
                    {"de": "4 Dimensionen, ~3 Minuten", "en": "4 dimensions, ~3 minutes"},
                    {"de": "Sofort-Score von 0–100", "en": "Instant 0–100 score"},
                    {"de": "Konkrete nächste Schritte", "en": "Actionable next steps"},
                ]
            ),
        )
    )
    session.add(
        QuizResultConfig(
            quiz_id=quiz.id,
            intro_de="Ihr Agentic-AI-Readiness-Ergebnis",
            intro_en="Your Agentic AI Readiness result",
            show_dimension_breakdown=True,
            email_subject_de="Ihr Agentic AI Readiness Score: {score}/100",
            email_subject_en="Your Agentic AI Readiness Score: {score}/100",
            email_body_de=(
                "Hallo {name},\n\nIhr Readiness-Score liegt bei {score}/100 ({tier}).\n"
                "Vollständige Auswertung: {url}\n\n// Agentic Reach"
            ),
            email_body_en=(
                "Hi {name},\n\nyour readiness score is {score}/100 ({tier}).\n"
                "Full evaluation: {url}\n\n// Agentic Reach"
            ),
            notify_emails="leads@agentic-reach.com",
        )
    )
    session.commit()


def main() -> int:
    create_db()
    with Session(engine) as session:
        existing = session.exec(select(Quiz).where(Quiz.slug == SLUG)).first()
        if existing:
            print(f"quiz {SLUG!r} already seeded (id={existing.id}) — nothing to do.")
            return 0
        _seed(session)
    print(f"seeded flagship quiz {SLUG!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
