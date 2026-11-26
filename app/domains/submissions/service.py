"""Submissions domain — lead persistence + read views.

Receives already-computed scores as primitives (never the quizzes domain's
objects — domain independence) and persists the durable lead row. The lead
pipeline (local is this commit; CRM + email are added in Phase 5) is fired by
the interface layer after `create_submission` returns.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import func, or_
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
        quiz_id=submission.quiz_id,
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


# Providers that ignore dots in the local part (v.ictim@ == victim@).
_DOTLESS_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
# Upper bound on rows compared per duplicate check; the per-IP submit limit keeps
# the real count far below it.
_DEDUP_SCAN_LIMIT = 1000


def canonical_mailbox(email: str) -> str:
    """Delivery-equivalence key for the duplicate check (never stored/shown).

    Lowercased; the local part loses everything from the first '+'
    (sub-addressing); for gmail.com / googlemail.com dots are dropped as well
    and googlemail.com folds into gmail.com. `victim+1@example.com` and
    `Victim@example.com` therefore land in the same mailbox key.
    """
    local, sep, domain = email.strip().lower().rpartition("@")
    if not sep:
        return email.strip().lower()
    local = local.split("+", 1)[0]
    if domain in _DOTLESS_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def has_recent_submission(
    session: Session,
    *,
    quiz_id: int,
    email: str,
    within_seconds: int,
    exclude_id: int | None = None,
) -> bool:
    """True iff another lead for the same mailbox took this quiz within the last
    `within_seconds` — the submit handler then does not fan the duplicate out to
    CRM / email again (SEC-003). Mailboxes are compared by `canonical_mailbox`,
    so plus-addressing / Gmail dot variants do not bypass the window."""
    if within_seconds <= 0 or not email:
        return False
    key = canonical_mailbox(email)
    domain = key.rpartition("@")[2]
    domains = list(_DOTLESS_DOMAINS) if domain in _DOTLESS_DOMAINS else [domain]
    since = utcnow() - timedelta(seconds=within_seconds)
    stmt = select(Submission.email).where(
        Submission.quiz_id == quiz_id,
        col(Submission.email).is_not(None),
        col(Submission.created_at) >= since,
        or_(*[func.lower(Submission.email).like(f"%@{d}") for d in domains]),
    )
    if exclude_id is not None:
        stmt = stmt.where(Submission.id != exclude_id)
    rows = session.exec(stmt.order_by(col(Submission.created_at).desc()).limit(_DEDUP_SCAN_LIMIT))
    return any(other and canonical_mailbox(other) == key for other in rows)


def stored_answers(submission: Submission) -> dict[int, int]:
    """The persisted {question_id: option_id} map (JSON keys are strings)."""
    raw = json.loads(submission.answers_json or "{}")
    return {int(k): int(v) for k, v in raw.items()}


def stored_dimension_scores(submission: Submission) -> dict[str, int]:
    raw = json.loads(submission.dimension_scores_json or "{}")
    return {str(k): int(v) for k, v in raw.items()}
