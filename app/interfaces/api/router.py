"""interfaces.api.router — public JSON API for the quiz player.

`GET /api/quiz/{slug}` returns the player payload (questions + options, no
weights). `POST /api/quiz/{slug}/submit` is added in Phase 4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.domains.quizzes import service as quizzes_service
from app.domains.quizzes.schemas import QuizPublic
from app.domains.submissions import pipeline
from app.domains.submissions import service as submissions_service
from app.domains.submissions.schemas import SubmitRequest

router = APIRouter(prefix="/api", tags=["api"])


def _result_url(public_id: str) -> str:
    host = get_settings().app_host
    return f"https://{host}/r/{public_id}" if host else f"/r/{public_id}"


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
    slug: str, payload: SubmitRequest, session: Session = Depends(get_session)
) -> dict[str, str]:
    quiz = quizzes_service.get_published_quiz(session, slug)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    assert quiz.id is not None

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

    # Fan the lead out to CRM + email (local row already committed; both legs
    # skip cleanly when unconfigured and never block the redirect).
    email_cfg = quizzes_service.get_result_email_config(session, quiz, payload.lang)
    pipeline.dispatch(
        session,
        submission,
        email_subject=email_cfg.subject_template,
        email_body=email_cfg.body_template,
        notify_emails=email_cfg.notify_emails,
        result_url=_result_url(submission.public_id),
    )
    return {"public_id": submission.public_id, "redirect": f"/r/{submission.public_id}"}
