"""interfaces.web.admin — the configuration UI (quiz / scoring / copy / leads).

Every route is gated by `require_admin` (router-level dependency). Mutations are
POST + RedirectResponse (back to the editor). Handlers call the quizzes admin
module + the submissions service; they never import domain models.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import require_admin
from app.domains.quizzes import admin as quizzes_admin
from app.domains.quizzes import service as quizzes_service
from app.domains.submissions import pipeline
from app.domains.submissions import service as submissions_service

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
templates = Jinja2Templates(directory="templates")


def _back(quiz_id: int) -> RedirectResponse:
    return RedirectResponse(f"/admin/quizzes/{quiz_id}", status_code=303)


# --- Quiz list + create ----------------------------------------------------
@router.get("", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    quizzes = quizzes_admin.list_quizzes(session)
    return templates.TemplateResponse(request, "admin/quiz_list.html", {"quizzes": quizzes})


@router.post("/quizzes")
def create_quiz(
    slug: str = Form(...),
    title_de: str = Form(""),
    title_en: str = Form(""),
    session: Session = Depends(get_session),
):
    quiz = quizzes_admin.create_quiz(session, slug, title_de, title_en)
    assert quiz.id is not None
    return _back(quiz.id)


# --- Quiz editor -----------------------------------------------------------
@router.get("/quizzes/{quiz_id}", response_class=HTMLResponse)
def edit_quiz(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = quizzes_admin.get_quiz(session, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    questions = [
        {"q": q, "options": quizzes_admin.get_options(session, q.id)}
        for q in quizzes_admin.get_questions(session, quiz_id)
    ]
    return templates.TemplateResponse(
        request,
        "admin/quiz_edit.html",
        {
            "quiz": quiz,
            "landing": quizzes_admin.get_landing(session, quiz_id),
            "result_cfg": quizzes_admin.get_result_config(session, quiz_id),
            "dimensions": quizzes_admin.get_dimensions(session, quiz_id),
            "questions": questions,
            "tiers": quizzes_admin.get_tiers(session, quiz_id),
        },
    )


@router.post("/quizzes/{quiz_id}/meta")
def update_meta(
    quiz_id: int,
    slug: str = Form(...),
    title_de: str = Form(""),
    title_en: str = Form(""),
    default_lang: str = Form("de"),
    estimated_minutes: int = Form(3),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_quiz_meta(
        session,
        quiz_id,
        slug=slug,
        title_de=title_de,
        title_en=title_en,
        default_lang=default_lang,
        estimated_minutes=estimated_minutes,
    )
    return _back(quiz_id)


@router.post("/quizzes/{quiz_id}/publish")
def publish(quiz_id: int, session: Session = Depends(get_session)):
    quizzes_admin.toggle_publish(session, quiz_id)
    return _back(quiz_id)


@router.post("/quizzes/{quiz_id}/clone")
def clone(quiz_id: int, session: Session = Depends(get_session)):
    quizzes_admin.clone_quiz(session, quiz_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/quizzes/{quiz_id}/delete")
def delete_quiz(quiz_id: int, session: Session = Depends(get_session)):
    quizzes_admin.delete_quiz(session, quiz_id)
    return RedirectResponse("/admin", status_code=303)


# --- Landing + result config ----------------------------------------------
@router.post("/quizzes/{quiz_id}/landing")
def update_landing(
    quiz_id: int,
    hero_eyebrow_de: str = Form(""),
    hero_eyebrow_en: str = Form(""),
    hero_headline_de: str = Form(""),
    hero_headline_en: str = Form(""),
    hero_subline_de: str = Form(""),
    hero_subline_en: str = Form(""),
    cta_label_de: str = Form(""),
    cta_label_en: str = Form(""),
    benefits_json: str = Form("[]"),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_landing(
        session,
        quiz_id,
        hero_eyebrow_de=hero_eyebrow_de,
        hero_eyebrow_en=hero_eyebrow_en,
        hero_headline_de=hero_headline_de,
        hero_headline_en=hero_headline_en,
        hero_subline_de=hero_subline_de,
        hero_subline_en=hero_subline_en,
        cta_label_de=cta_label_de,
        cta_label_en=cta_label_en,
        benefits_json=benefits_json,
    )
    return _back(quiz_id)


@router.post("/quizzes/{quiz_id}/result")
def update_result(
    quiz_id: int,
    intro_de: str = Form(""),
    intro_en: str = Form(""),
    show_dimension_breakdown: str | None = Form(None),
    email_subject_de: str = Form(""),
    email_subject_en: str = Form(""),
    email_body_template: str = Form(""),
    notify_emails: str = Form(""),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_result_config(
        session,
        quiz_id,
        intro_de=intro_de,
        intro_en=intro_en,
        show_dimension_breakdown=show_dimension_breakdown is not None,
        email_subject_de=email_subject_de,
        email_subject_en=email_subject_en,
        email_body_template=email_body_template,
        notify_emails=notify_emails,
    )
    return _back(quiz_id)


# --- Dimensions ------------------------------------------------------------
@router.post("/quizzes/{quiz_id}/dimensions")
def add_dimension(
    quiz_id: int,
    key: str = Form(...),
    name_de: str = Form(""),
    name_en: str = Form(""),
    weight: float = Form(1.0),
    session: Session = Depends(get_session),
):
    quizzes_admin.add_dimension(session, quiz_id, key, name_de, name_en, weight)
    return _back(quiz_id)


@router.post("/dimensions/{dim_id}")
def update_dimension(
    dim_id: int,
    quiz_id: int = Form(...),
    key: str = Form(...),
    name_de: str = Form(""),
    name_en: str = Form(""),
    weight: float = Form(1.0),
    position: int = Form(0),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_dimension(
        session, dim_id, key=key, name_de=name_de, name_en=name_en, weight=weight, position=position
    )
    return _back(quiz_id)


@router.post("/dimensions/{dim_id}/delete")
def delete_dimension(
    dim_id: int, quiz_id: int = Form(...), session: Session = Depends(get_session)
):
    quizzes_admin.delete_dimension(session, dim_id)
    return _back(quiz_id)


# --- Questions + options ---------------------------------------------------
@router.post("/quizzes/{quiz_id}/questions")
def add_question(
    quiz_id: int,
    dimension_id: int = Form(...),
    text_de: str = Form(""),
    text_en: str = Form(""),
    session: Session = Depends(get_session),
):
    quizzes_admin.add_question(session, quiz_id, dimension_id, text_de, text_en)
    return _back(quiz_id)


@router.post("/questions/{question_id}")
def update_question(
    question_id: int,
    quiz_id: int = Form(...),
    dimension_id: int = Form(...),
    text_de: str = Form(""),
    text_en: str = Form(""),
    help_de: str = Form(""),
    help_en: str = Form(""),
    position: int = Form(0),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_question(
        session,
        question_id,
        dimension_id=dimension_id,
        text_de=text_de,
        text_en=text_en,
        help_de=help_de,
        help_en=help_en,
        position=position,
    )
    return _back(quiz_id)


@router.post("/questions/{question_id}/delete")
def delete_question(
    question_id: int, quiz_id: int = Form(...), session: Session = Depends(get_session)
):
    quizzes_admin.delete_question(session, question_id)
    return _back(quiz_id)


@router.post("/questions/{question_id}/options")
def add_option(
    question_id: int,
    quiz_id: int = Form(...),
    label_de: str = Form(""),
    label_en: str = Form(""),
    weight: float = Form(0.0),
    session: Session = Depends(get_session),
):
    quizzes_admin.add_option(session, question_id, label_de, label_en, weight)
    return _back(quiz_id)


@router.post("/options/{option_id}")
def update_option(
    option_id: int,
    quiz_id: int = Form(...),
    label_de: str = Form(""),
    label_en: str = Form(""),
    weight: float = Form(0.0),
    position: int = Form(0),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_option(
        session, option_id, label_de=label_de, label_en=label_en, weight=weight, position=position
    )
    return _back(quiz_id)


@router.post("/options/{option_id}/delete")
def delete_option(
    option_id: int, quiz_id: int = Form(...), session: Session = Depends(get_session)
):
    quizzes_admin.delete_option(session, option_id)
    return _back(quiz_id)


# --- Tiers -----------------------------------------------------------------
@router.post("/quizzes/{quiz_id}/tiers")
def add_tier(
    quiz_id: int,
    name_de: str = Form(""),
    name_en: str = Form(""),
    min_score: int = Form(0),
    max_score: int = Form(100),
    session: Session = Depends(get_session),
):
    quizzes_admin.add_tier(session, quiz_id, name_de, name_en, min_score, max_score)
    return _back(quiz_id)


@router.post("/tiers/{tier_id}")
def update_tier(
    tier_id: int,
    quiz_id: int = Form(...),
    name_de: str = Form(""),
    name_en: str = Form(""),
    min_score: int = Form(0),
    max_score: int = Form(100),
    headline_de: str = Form(""),
    headline_en: str = Form(""),
    body_de: str = Form(""),
    body_en: str = Form(""),
    cta_label_de: str = Form(""),
    cta_label_en: str = Form(""),
    cta_url: str = Form(""),
    position: int = Form(0),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_tier(
        session,
        tier_id,
        name_de=name_de,
        name_en=name_en,
        min_score=min_score,
        max_score=max_score,
        headline_de=headline_de,
        headline_en=headline_en,
        body_de=body_de,
        body_en=body_en,
        cta_label_de=cta_label_de,
        cta_label_en=cta_label_en,
        cta_url=cta_url,
        position=position,
    )
    return _back(quiz_id)


@router.post("/tiers/{tier_id}/delete")
def delete_tier(tier_id: int, quiz_id: int = Form(...), session: Session = Depends(get_session)):
    quizzes_admin.delete_tier(session, tier_id)
    return _back(quiz_id)


# --- Leads -----------------------------------------------------------------
@router.get("/quizzes/{quiz_id}/leads", response_class=HTMLResponse)
def leads(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = quizzes_admin.get_quiz(session, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    return templates.TemplateResponse(
        request,
        "admin/leads.html",
        {"quiz": quiz, "leads": submissions_service.list_submissions(session, quiz_id)},
    )


@router.get("/quizzes/{quiz_id}/leads.csv")
def leads_csv(quiz_id: int, session: Session = Depends(get_session)):
    rows = submissions_service.list_submissions(session, quiz_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "created_at",
            "email",
            "name",
            "company",
            "score",
            "tier",
            "consent",
            "crm_pushed",
            "email_sent",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.created_at.isoformat(),
                r.email or "",
                r.name or "",
                r.company or "",
                r.overall_score,
                r.tier_name or "",
                r.consent,
                r.crm_pushed,
                r.email_sent,
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="leads-{quiz_id}.csv"'},
    )


@router.post("/submissions/{submission_id}/retry")
def retry_pipeline(
    submission_id: int, quiz_id: int = Form(...), session: Session = Depends(get_session)
):
    submission = submissions_service.get_submission(session, submission_id)
    quiz = quizzes_admin.get_quiz(session, quiz_id)
    if submission is not None and quiz is not None:
        email_cfg = quizzes_service.get_result_email_config(session, quiz, submission.lang)
        host = get_settings().app_host
        result_url = (
            f"https://{host}/r/{submission.public_id}" if host else f"/r/{submission.public_id}"
        )
        pipeline.dispatch(
            session,
            submission,
            email_subject=email_cfg.subject_template,
            email_body=email_cfg.body_template,
            notify_emails=email_cfg.notify_emails,
            result_url=result_url,
        )
    return RedirectResponse(f"/admin/quizzes/{quiz_id}/leads", status_code=303)
