"""interfaces.api.router — public JSON API for the quiz player.

`GET /api/quiz/{slug}` returns the player payload (questions + options, no
weights). `POST /api/quiz/{slug}/submit` is added in Phase 4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.core.security import client_key, rate_limit, submit_throttle
from app.domains.quizzes import service as quizzes_service
from app.domains.quizzes.schemas import QuizPublic
from app.domains.submissions import pipeline
from app.domains.submissions import service as submissions_service
from app.domains.submissions.schemas import SubmitRequest
from app.interfaces import lead_mail

router = APIRouter(prefix="/api", tags=["api"])
log = get_logger("interfaces.api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/quiz/{slug}", response_model=QuizPublic)
def get_quiz(slug: str, session: Session = Depends(get_session)) -> QuizPublic:
    quiz = quizzes_service.get_published_quiz(session, slug)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    return quizzes_service.build_player_payload(session, quiz)


@router.post("/quiz/{slug}/submit")
def submit(
    slug: str,
    payload: SubmitRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Score + store the lead, then fan it out (CRM + mails).

    Abuse controls (SEC-002/003/017): the DTO admits exactly one valid email and
    bounded single-line name/company; per-IP rate limit (429); the answers must
    be a complete answer sheet of THIS quiz (422); a repeat of the same email on
    the same quiz inside SUBMIT_DEDUP_WINDOW_SECONDS is stored but not fanned
    out again. The request body itself is capped by BodySizeLimitMiddleware.
    """
    settings = get_settings()
    wait = rate_limit(
        submit_throttle,
        client_key(request),
        [(settings.submit_max_per_minute, 60), (settings.submit_max_per_hour, 3600)],
    )
    if wait:
        raise HTTPException(
            status_code=429,
            detail="too many submissions, please try again later",
            headers={"Retry-After": str(wait)},
        )

    quiz = quizzes_service.get_published_quiz(session, slug)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    assert quiz.id is not None

    problems = quizzes_service.answer_errors(session, quiz, payload.answers)
    if problems:
        raise HTTPException(status_code=422, detail=problems[:10])

    duplicate = submissions_service.has_recent_submission(
        session,
        quiz_id=quiz.id,
        email=payload.email,
        within_seconds=settings.submit_dedup_window_seconds,
    )

    score = quizzes_service.score_submission(session, quiz, payload.answers)
    submission = submissions_service.create_submission(
        session,
        quiz_id=quiz.id,
        quiz_slug=slug,
        lang=payload.lang,
        answers=payload.answers,
        overall_score=score.overall,
        dimension_scores=score.dimension_scores,
        tier_id=score.tier_id,
        tier_name=score.tier_name,
        email=payload.email,
        name=payload.name,
        company=payload.company,
        consent=payload.consent,
    )
    done = {"public_id": submission.public_id, "redirect": f"/r/{submission.public_id}"}

    # The local row is committed (source of truth). Nothing after this point may
    # fail the visitor's request (SEC-011): both legs are fault-isolated inside
    # the pipeline, and rendering problems are logged, not raised.
    try:
        if duplicate:
            pipeline.mark_duplicate(session, submission)
        else:
            lead_mail.dispatch_lead(session, submission, quiz)
    except Exception:
        log.exception("Lead fan-out failed for submission %s", submission.public_id)
    return done
