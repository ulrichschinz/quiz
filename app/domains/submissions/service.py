"""Submissions domain — lead persistence + read views.

Receives already-computed scores as primitives (never the quizzes domain's
objects — domain independence) and persists the durable lead row. The lead
pipeline (local is this commit; CRM + email are added in Phase 5) is fired by
the interface layer after `create_submission` returns.
"""

from __future__ import annotations

import json
import uuid

from sqlmodel import Session, col, select

from app.domains.submissions.models import Submission
from app.domains.submissions.schemas import SubmissionView
from app.shared.clock import utcnow


def create_submission(
    session: Session,
    *,
    quiz_id: int,
    quiz_slug: str,
    lang: str,
    answers: dict[int, int],
    overall_score: int,
    dimension_scores: dict[str, int],
    tier_id: int | None,
    tier_name: str | None,
    email: str | None,
    name: str | None,
    company: str | None,
    consent: bool,
) -> Submission:
    """Persist the lead + scores. This local write is the source of truth and
    must succeed before the visitor is redirected to their results."""
    submission = Submission(
        public_id=uuid.uuid4().hex,
        quiz_id=quiz_id,
        quiz_slug=quiz_slug,
        lang=lang,
        answers_json=json.dumps(answers),
        overall_score=overall_score,
        dimension_scores_json=json.dumps(dimension_scores),
        tier_id=tier_id,
        tier_name=tier_name,
        email=email,
        name=name,
        company=company,
        consent=consent,
        completed_at=utcnow(),
    )
    session.add(submission)
    session.commit()
    session.refresh(submission)
    return submission


def get_public_submission(session: Session, public_id: str) -> SubmissionView | None:
    submission = session.exec(select(Submission).where(Submission.public_id == public_id)).first()
    if submission is None:
        return None
    return SubmissionView(
        public_id=submission.public_id,
        quiz_slug=submission.quiz_slug,
        lang=submission.lang,
        overall_score=submission.overall_score,
        dimension_scores=json.loads(submission.dimension_scores_json or "{}"),
        tier_id=submission.tier_id,
        tier_name=submission.tier_name,
        name=submission.name,
        email=submission.email,
        company=submission.company,
    )


def list_submissions(session: Session, quiz_id: int) -> list[Submission]:
    """All leads for a quiz, newest first (admin list + CSV export)."""
    return list(
        session.exec(
            select(Submission)
            .where(Submission.quiz_id == quiz_id)
            .order_by(col(Submission.created_at).desc())
        ).all()
    )


def get_submission(session: Session, submission_id: int) -> Submission | None:
    return session.get(Submission, submission_id)
