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
from app.shared import emails

router = APIRouter(prefix="/api", tags=["api"])


def _result_url(public_id: str) -> str:
    host = get_settings().app_host
    return f"https://{host}/r/{public_id}" if host else f"/r/{public_id}"


def _logo_url() -> str:
    host = get_settings().app_host
    return f"https://{host}{emails.LOGO_PATH}" if host else emails.LOGO_PATH


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
    result_url = _result_url(submission.public_id)
    result_view = quizzes_service.get_result_view(
        session, slug, score.tier_id, score.dimension_scores, payload.lang
    )

    # The interface layer owns templating: substitute the placeholders once and
    # render the branded HTML, then hand finished bytes to the dumb pipeline.
    customer_subject = email_cfg.subject_template.format(score=submission.overall_score)
    customer_text = email_cfg.body_template.format(
        name=submission.name or "",
        score=submission.overall_score,
        tier=submission.tier_name or "",
        url=result_url,
    )
    customer_html = emails.render_customer_email(
        lang=payload.lang,
        intro_text=customer_text,
        overall_score=submission.overall_score,
        tier_name=result_view.tier_name,
        tier_headline=result_view.tier_headline,
        tier_body=result_view.tier_body,
        dimensions=[(d.name, d.score) for d in result_view.dimensions],
        show_breakdown=result_view.show_breakdown,
        cta_label=result_view.cta_label,
        cta_url=result_view.cta_url,
        result_url=result_url,
        logo_url=_logo_url(),
    )

    # Internal team notification: full answer breakdown so the team can prep.
    breakdown = quizzes_service.get_answer_breakdown(
        session, quiz, payload.answers, score.dimension_scores, payload.lang
    )
    team_html, team_text = emails.render_team_email(
        overall_score=submission.overall_score,
        tier_name=submission.tier_name,
        breakdown=breakdown,
        lead_name=submission.name,
        lead_email=submission.email,
        lead_company=submission.company,
        consent=submission.consent,
        result_url=result_url,
        logo_url=_logo_url(),
    )

    pipeline.dispatch(
        session,
        submission,
        customer_subject=customer_subject,
        customer_text=customer_text,
        customer_html=customer_html,
        team_subject=f"Neuer Lead: {submission.overall_score}/100 — {submission.company or submission.name or submission.email}",
        team_text=team_text,
        team_html=team_html,
        notify_emails=email_cfg.notify_emails,
        result_url=result_url,
    )
    return {"public_id": submission.public_id, "redirect": f"/r/{submission.public_id}"}
