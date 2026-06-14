"""interfaces.web.public — public-facing pages (landing, quiz player, results).

- `GET /`                 → redirect to the first published quiz, else a
                            branded "coming soon" landing.
- `GET /q/{slug}`         → data-driven landing (QuizLandingConfig).
- `GET /q/{slug}/take`    → the quiz player shell (player.js fetches the JSON).

The results page (`GET /r/{public_id}`) is added in Phase 4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.core.db import get_session
from app.domains.quizzes import service as quizzes_service
from app.domains.submissions import service as submissions_service
from app.shared.charts import radar_geometry
from app.shared.scoring_display import score_level

router = APIRouter()
templates = Jinja2Templates(directory="templates")
# Available in every template: score_level(0-100) -> "low"|"mid"|"high" drives
# the traffic-light colour, radar_geometry builds the results-page net chart.
templates.env.globals["score_level"] = score_level
templates.env.globals["radar_geometry"] = radar_geometry


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    quiz = quizzes_service.get_first_published_quiz(session)
    if quiz is not None:
        return RedirectResponse(f"/q/{quiz.slug}", status_code=303)
    return templates.TemplateResponse(request, "public/landing.html", {"landing": None})


@router.get("/q/{slug}", response_class=HTMLResponse)
def landing(slug: str, request: Request, session: Session = Depends(get_session)):
    quiz = quizzes_service.get_published_quiz(session, slug)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    view = quizzes_service.get_landing_view(session, quiz)
    # `lang` seeds the server-rendered fallback; the client toggle treats
    # ?lang=de|en as the source of truth (see base.html).
    return templates.TemplateResponse(
        request,
        "public/landing.html",
        {"landing": view, "lang": quiz.default_lang},
    )


@router.get("/q/{slug}/take", response_class=HTMLResponse)
def take(slug: str, request: Request, session: Session = Depends(get_session)):
    quiz = quizzes_service.get_published_quiz(session, slug)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    return templates.TemplateResponse(
        request,
        "public/quiz.html",
        {"slug": slug, "default_lang": quiz.default_lang, "lang": quiz.default_lang},
    )


@router.get("/r/{public_id}", response_class=HTMLResponse)
def results(public_id: str, request: Request, session: Session = Depends(get_session)):
    view = submissions_service.get_public_submission(session, public_id)
    if view is None:
        raise HTTPException(status_code=404, detail="result not found")
    result = quizzes_service.get_result_view(
        session, view.quiz_slug, view.tier_id, view.dimension_scores, view.lang
    )
    return templates.TemplateResponse(
        request,
        "public/results.html",
        {"sub": view, "result": result, "lang": view.lang},
    )
