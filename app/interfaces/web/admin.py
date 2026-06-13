"""interfaces.web.admin — the configuration UI (quiz / scoring / copy / leads).

Every route is gated by `require_admin` (router-level dependency). Mutations are
POST + RedirectResponse (back to the editor). Handlers call the quizzes admin
module + the submissions service; they never import domain models.
"""

from __future__ import annotations

import csv
import io
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
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


def _redirect_back(request: Request, quiz_id: int) -> RedirectResponse:
    """Return the user to the studio area they came from (the studio splits the
    editor into per-area routes), falling back to the overview. Used for full-page
    navigations (publish) and the no-JS POST fallback."""
    ref = request.headers.get("referer")
    if ref:
        path = urlparse(ref).path
        if path.startswith(f"/admin/quizzes/{quiz_id}"):
            return RedirectResponse(path, status_code=303)
    return _back(quiz_id)


# --- inline-save plumbing (Phase 1) ----------------------------------------
# The editor's per-entity forms POST with an `X-Inline: 1` header (set by
# static/admin/admin-workspace.js). When present we answer with a fragment /
# 204 / 422 instead of a 303 full-page redirect, so the page never reloads or
# jumps. Without the header (no JS) every handler keeps its old `_back()` path.
def _is_inline(request: Request) -> bool:
    return request.headers.get("x-inline") == "1"


def _parse_weight(raw: str) -> float:
    """Accept German decimals ("0,5") — there is no global 422 handler, so a raw
    `float` Form field would explode on a comma. Raises ValueError on garbage."""
    return float(raw.strip().replace(",", "."))


def _parse_int(raw: str) -> int:
    """Tolerant int parse for score fields. A raw `int` Form field would 422 on an
    emptied number input; we route those to a friendly message instead."""
    return int(raw.strip())


def _slugify(text: str) -> str:
    """Derive a dimension's internal code from its German name, so the user never
    has to type a 'Key'. Lowercase, ascii-ish, underscores."""
    out = []
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("_")
    return "_".join(filter(None, "".join(out).split("_")))


def _invalid(request: Request, quiz_id: int, message: str) -> Response:
    """Validation failure: a friendly 422 for the inline path, a silent redirect
    (data simply not saved) for the no-JS fallback."""
    if _is_inline(request):
        return PlainTextResponse(message, status_code=422)
    return _redirect_back(request, quiz_id)


def _fragment(
    request: Request, session: Session, quiz_id: int, template: str, ctx: dict[str, object]
) -> HTMLResponse:
    quiz = quizzes_admin.get_quiz(session, quiz_id)
    return templates.TemplateResponse(request, template, {"quiz": quiz, **ctx})


def _saved(request: Request, quiz_id: int) -> Response:
    """No-DOM-change success (singleton save / delete)."""
    if _is_inline(request):
        return Response(status_code=204)
    return _redirect_back(request, quiz_id)


def _dimensions_response(request: Request, session: Session, quiz_id: int) -> Response:
    """Re-render the whole Bereiche + Themen-Anteile section. Every dimension
    mutation rebalances the percent shares, so a single-row swap would desync the
    sliders — the section is the inline-replace unit."""
    if _is_inline(request):
        return _fragment(
            request,
            session,
            quiz_id,
            "admin/_dimensions_section.html",
            {"dimensions": quizzes_admin.get_dimensions(session, quiz_id)},
        )
    return _redirect_back(request, quiz_id)


def _options_response(
    request: Request, session: Session, quiz_id: int, question_id: int
) -> Response:
    """Re-render the whole answer-options section. Adding / deleting / reordering
    re-derives every option's weight from the ranking, so the section (not a row)
    is the inline-replace unit."""
    if _is_inline(request):
        question = quizzes_admin.get_question(session, question_id)
        return _fragment(
            request,
            session,
            quiz_id,
            "admin/_options_section.html",
            {"question": question, "options": quizzes_admin.get_options(session, question_id)},
        )
    return _redirect_back(request, quiz_id)


def _question_quiz_id(session: Session, question_id: int) -> int | None:
    """Resolve the owning quiz_id from a question (trusted source), so option
    routes never render against a quiz_id smuggled through the form."""
    q = quizzes_admin.get_question(session, question_id)
    return q.quiz_id if q is not None else None


def _parse_weights(form: dict[str, str]) -> dict[int, float]:
    """Pull `weight_<dim_id>` slider fields out of a posted form into {id: value}.
    Unparseable values are skipped (the server renormalises whatever it gets)."""
    out: dict[int, float] = {}
    for key, raw in form.items():
        if not key.startswith("weight_"):
            continue
        try:
            out[int(key[len("weight_") :])] = _parse_weight(raw)
        except ValueError:
            continue
    return out


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


# --- Quiz Studio (one focused GET page per area; POSTs are shared below) ----
def _load(session: Session, quiz_id: int):
    quiz = quizzes_admin.get_quiz(session, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    return quiz


def _completeness(session: Session, quiz_id: int):
    """Counts + a 'startklar?' checklist for the overview, computed in one place."""
    dims = quizzes_admin.get_dimensions(session, quiz_id)
    questions = quizzes_admin.get_questions(session, quiz_id)
    tiers = quizzes_admin.get_tiers(session, quiz_id)
    landing = quizzes_admin.get_landing(session, quiz_id)
    result_cfg = quizzes_admin.get_result_config(session, quiz_id)
    leads = submissions_service.list_submissions(session, quiz_id)
    q_missing_options = sum(1 for q in questions if not quizzes_admin.get_options(session, q.id))
    base = f"/admin/quizzes/{quiz_id}"
    checklist = [
        {"label": "Mindestens ein Bereich angelegt", "done": bool(dims), "link": f"{base}/scoring"},
        {
            "label": "Mindestens eine Frage angelegt",
            "done": bool(questions),
            "link": f"{base}/questions",
        },
        {
            "label": "Jede Frage hat Antworten",
            "done": bool(questions) and q_missing_options == 0,
            "link": f"{base}/questions",
        },
        {"label": "Bewertungs-Stufen angelegt", "done": bool(tiers), "link": f"{base}/scoring"},
        {
            "label": "Landingpage-Überschrift gefüllt",
            "done": bool(landing and landing.hero_headline_de),
            "link": f"{base}/landing",
        },
        {
            "label": "Ergebnis-E-Mail-Betreff gefüllt",
            "done": bool(result_cfg and result_cfg.email_subject_de),
            "link": f"{base}/results",
        },
    ]
    done = sum(1 for c in checklist if c["done"])
    percent = round(done / len(checklist) * 100)
    stats = {"questions": len(questions), "dimensions": len(dims), "leads": len(leads)}
    return stats, checklist, percent, leads


@router.get("/quizzes/{quiz_id}", response_class=HTMLResponse)
def overview(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = _load(session, quiz_id)
    stats, checklist, percent, leads = _completeness(session, quiz_id)
    recent = sorted(leads, key=lambda r: r.created_at, reverse=True)[:5]
    return templates.TemplateResponse(
        request,
        "admin/overview.html",
        {
            "quiz": quiz,
            "active": "overview",
            "stats": stats,
            "checklist": checklist,
            "percent": percent,
            "recent_leads": recent,
        },
    )


def _render_questions(request: Request, session: Session, quiz, focused_qid: int | None):
    dims = quizzes_admin.get_dimensions(session, quiz.id)
    all_q = quizzes_admin.get_questions(session, quiz.id)
    by_dim: dict[int, list[dict[str, object]]] = {}
    for q in all_q:
        opts = quizzes_admin.get_options(session, q.id)
        by_dim.setdefault(q.dimension_id, []).append(
            {"q": q, "option_count": len(opts), "has_options": bool(opts)}
        )
    groups = [{"dimension": d, "questions": by_dim.get(d.id, [])} for d in dims]

    target = focused_qid if focused_qid is not None else (all_q[0].id if all_q else None)
    focused = None
    if target is not None:
        fq = quizzes_admin.get_question(session, target)
        if fq is not None and fq.quiz_id == quiz.id:
            focused = {"q": fq, "options": quizzes_admin.get_options(session, fq.id)}
    return templates.TemplateResponse(
        request,
        "admin/questions.html",
        {
            "quiz": quiz,
            "active": "questions",
            "dimensions": dims,
            "groups": groups,
            "focused": focused,
        },
    )


@router.get("/quizzes/{quiz_id}/questions", response_class=HTMLResponse)
def questions_page(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    return _render_questions(request, session, _load(session, quiz_id), None)


@router.get("/quizzes/{quiz_id}/questions/{question_id}", response_class=HTMLResponse)
def question_focus(
    quiz_id: int, question_id: int, request: Request, session: Session = Depends(get_session)
):
    quiz = _load(session, quiz_id)
    fq = quizzes_admin.get_question(session, question_id)
    if fq is None or fq.quiz_id != quiz.id:
        return RedirectResponse(f"/admin/quizzes/{quiz_id}/questions", status_code=303)
    return _render_questions(request, session, quiz, question_id)


@router.get("/quizzes/{quiz_id}/scoring", response_class=HTMLResponse)
def scoring_page(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = _load(session, quiz_id)
    return templates.TemplateResponse(
        request,
        "admin/scoring.html",
        {
            "quiz": quiz,
            "active": "scoring",
            "dimensions": quizzes_admin.get_dimensions(session, quiz_id),
            "tiers": quizzes_admin.get_tiers(session, quiz_id),
        },
    )


@router.get("/quizzes/{quiz_id}/landing", response_class=HTMLResponse)
def landing_page(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = _load(session, quiz_id)
    return templates.TemplateResponse(
        request,
        "admin/landing.html",
        {"quiz": quiz, "active": "landing", "landing": quizzes_admin.get_landing(session, quiz_id)},
    )


@router.get("/quizzes/{quiz_id}/results", response_class=HTMLResponse)
def results_page(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = _load(session, quiz_id)
    return templates.TemplateResponse(
        request,
        "admin/results.html",
        {
            "quiz": quiz,
            "active": "results",
            "result_cfg": quizzes_admin.get_result_config(session, quiz_id),
        },
    )


@router.get("/quizzes/{quiz_id}/settings", response_class=HTMLResponse)
def settings_page(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = _load(session, quiz_id)
    return templates.TemplateResponse(
        request, "admin/settings.html", {"quiz": quiz, "active": "settings"}
    )


@router.post("/quizzes/{quiz_id}/meta")
def update_meta(
    quiz_id: int,
    request: Request,
    slug: str = Form(""),
    title_de: str = Form(""),
    title_en: str = Form(""),
    default_lang: str = Form("de"),
    estimated_minutes: str = Form("3"),
    session: Session = Depends(get_session),
):
    if not slug.strip():
        return _invalid(request, quiz_id, "Adresse (Slug) darf nicht leer sein.")
    try:
        minutes = _parse_int(estimated_minutes)
    except ValueError:
        return _invalid(request, quiz_id, "Dauer muss eine ganze Zahl sein.")
    quizzes_admin.update_quiz_meta(
        session,
        quiz_id,
        slug=slug.strip(),
        title_de=title_de,
        title_en=title_en,
        default_lang=default_lang,
        estimated_minutes=minutes,
    )
    return _saved(request, quiz_id)


@router.post("/quizzes/{quiz_id}/publish")
def publish(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quizzes_admin.toggle_publish(session, quiz_id)
    return _redirect_back(request, quiz_id)


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
    request: Request,
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
    return _saved(request, quiz_id)


@router.post("/quizzes/{quiz_id}/result")
def update_result(
    quiz_id: int,
    request: Request,
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
    return _saved(request, quiz_id)


# --- Dimensions ------------------------------------------------------------
@router.post("/quizzes/{quiz_id}/dimensions")
def add_dimension(
    quiz_id: int,
    request: Request,
    name_de: str = Form(""),
    name_en: str = Form(""),
    key: str = Form(""),
    session: Session = Depends(get_session),
):
    # The user no longer types a "Key" — derive a stable internal code from the
    # name. The new Bereich gets an equal share automatically (sum stays 100).
    code = key.strip() or _slugify(name_de) or _slugify(name_en) or "bereich"
    quizzes_admin.add_dimension(session, quiz_id, code, name_de, name_en)
    return _dimensions_response(request, session, quiz_id)


@router.post("/dimensions/{dim_id}")
def update_dimension(
    dim_id: int,
    request: Request,
    quiz_id: int = Form(...),
    key: str = Form(...),
    name_de: str = Form(""),
    name_en: str = Form(""),
    position: int = Form(0),
    session: Session = Depends(get_session),
):
    quizzes_admin.update_dimension(
        session, dim_id, key=key, name_de=name_de, name_en=name_en, position=position
    )
    return _dimensions_response(request, session, quiz_id)


@router.post("/quizzes/{quiz_id}/dimensions/weights")
async def update_dimension_weights(
    quiz_id: int, request: Request, session: Session = Depends(get_session)
):
    """Save all Themen-Anteil sliders at once; the service renormalises to 100."""
    form = await request.form()
    quizzes_admin.set_dimension_weights(
        session, quiz_id, _parse_weights({k: str(v) for k, v in form.items()})
    )
    return _dimensions_response(request, session, quiz_id)


@router.post("/quizzes/{quiz_id}/dimensions/equalize")
def equalize_dimensions(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    """The 'Alle gleich verteilen' button — reset every Bereich to an equal share."""
    quizzes_admin.equalize_dimensions(session, quiz_id)
    return _dimensions_response(request, session, quiz_id)


@router.post("/dimensions/{dim_id}/delete")
def delete_dimension(
    dim_id: int,
    request: Request,
    quiz_id: int = Form(...),
    session: Session = Depends(get_session),
):
    quizzes_admin.delete_dimension(session, dim_id)
    return _dimensions_response(request, session, quiz_id)


# --- Questions + options ---------------------------------------------------
@router.post("/quizzes/{quiz_id}/questions")
def add_question(
    quiz_id: int,
    request: Request,
    dimension_id: int | None = Form(None),
    text_de: str = Form(""),
    text_en: str = Form(""),
    session: Session = Depends(get_session),
):
    # On a brand-new quiz the dimension <select> is empty, so nothing is posted.
    # Catch it ourselves (there is no global 422 handler) instead of leaking JSON.
    if dimension_id is None:
        return _invalid(request, quiz_id, "Bitte zuerst eine Dimension anlegen.")
    quizzes_admin.add_question(session, quiz_id, dimension_id, text_de, text_en)
    # Adding a question is full-page navigation in the studio: jump straight into
    # the new question's editor (master-detail right pane).
    new_q = quizzes_admin.get_questions(session, quiz_id)[-1]
    return RedirectResponse(f"/admin/quizzes/{quiz_id}/questions/{new_q.id}", status_code=303)


@router.post("/questions/{question_id}")
def update_question(
    question_id: int,
    request: Request,
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
    if _is_inline(request):
        q = quizzes_admin.get_question(session, question_id)
        if q is None:
            return Response(status_code=404)
        return _fragment(
            request,
            session,
            quiz_id,
            "admin/_question_form.html",
            {"q": q, "dimensions": quizzes_admin.get_dimensions(session, quiz_id)},
        )
    return _redirect_back(request, quiz_id)


@router.post("/questions/{question_id}/delete")
def delete_question(
    question_id: int,
    request: Request,
    quiz_id: int = Form(...),
    session: Session = Depends(get_session),
):
    quizzes_admin.delete_question(session, question_id)
    if _is_inline(request):
        return Response(status_code=204)
    # Full-page navigation: the focused question is gone — back to the list.
    return RedirectResponse(f"/admin/quizzes/{quiz_id}/questions", status_code=303)


@router.post("/questions/{question_id}/options")
def add_option(
    question_id: int,
    request: Request,
    label_de: str = Form(""),
    label_en: str = Form(""),
    session: Session = Depends(get_session),
):
    # No weight field any more — a new answer joins as the worst-ranked option
    # and the whole question's weights are re-derived from the ranking. quiz_id
    # is resolved from the question, never trusted from the form.
    quiz_id = _question_quiz_id(session, question_id)
    if quiz_id is None:
        return _invalid(request, 0, "Frage nicht gefunden.")
    quizzes_admin.add_option(session, question_id, label_de, label_en)
    return _options_response(request, session, quiz_id, question_id)


@router.post("/options/{option_id}")
def update_option(
    option_id: int,
    request: Request,
    label_de: str = Form(""),
    label_en: str = Form(""),
    position: int = Form(0),
    session: Session = Depends(get_session),
):
    o = quizzes_admin.get_option(session, option_id)
    if o is None:
        return _invalid(request, 0, "Antwort nicht gefunden.")
    question_id = o.question_id
    quiz_id = _question_quiz_id(session, question_id)
    if quiz_id is None:
        return _invalid(request, 0, "Frage nicht gefunden.")
    quizzes_admin.update_option(
        session, option_id, label_de=label_de, label_en=label_en, position=position
    )
    return _options_response(request, session, quiz_id, question_id)


@router.post("/questions/{question_id}/options/reorder")
async def reorder_options(
    question_id: int, request: Request, session: Session = Depends(get_session)
):
    """Drag & drop ranking: a best→worst list of option ids (`order=<id>` repeated)
    sets the ranks and re-derives weights."""
    quiz_id = _question_quiz_id(session, question_id)
    if quiz_id is None:
        return _invalid(request, 0, "Frage nicht gefunden.")
    form = await request.form()
    ordered_ids = [int(v) for v in form.getlist("order") if str(v).isdigit()]
    quizzes_admin.reorder_options(session, question_id, ordered_ids)
    return _options_response(request, session, quiz_id, question_id)


@router.post("/options/{option_id}/move")
def move_option(
    option_id: int,
    request: Request,
    direction: str = Form("up"),
    session: Session = Depends(get_session),
):
    """Keyboard- and no-JS-friendly ranking: nudge an option one step better
    ('up') or worse ('down')."""
    question_id = quizzes_admin.move_option(session, option_id, direction)
    if question_id is None:
        return _invalid(request, 0, "Antwort nicht gefunden.")
    quiz_id = _question_quiz_id(session, question_id)
    if quiz_id is None:
        return _invalid(request, 0, "Frage nicht gefunden.")
    return _options_response(request, session, quiz_id, question_id)


@router.post("/options/{option_id}/delete")
def delete_option(
    option_id: int,
    request: Request,
    quiz_id: int = Form(0),
    session: Session = Depends(get_session),
):
    o = quizzes_admin.get_option(session, option_id)
    question_id = o.question_id if o is not None else None
    # Resolve the quiz from the question before the delete, not from the form.
    resolved = _question_quiz_id(session, question_id) if question_id is not None else None
    quizzes_admin.delete_option(session, option_id)
    if question_id is None or resolved is None:
        return _saved(request, quiz_id)
    return _options_response(request, session, resolved, question_id)


# --- Tiers -----------------------------------------------------------------
@router.post("/quizzes/{quiz_id}/tiers")
def add_tier(
    quiz_id: int,
    request: Request,
    name_de: str = Form(""),
    name_en: str = Form(""),
    min_score: str = Form("0"),
    max_score: str = Form("100"),
    session: Session = Depends(get_session),
):
    try:
        mn, mx = _parse_int(min_score), _parse_int(max_score)
    except ValueError:
        return _invalid(request, quiz_id, "Min/Max müssen ganze Zahlen sein.")
    if mn > mx:
        return _invalid(request, quiz_id, "Min darf nicht größer als Max sein.")
    quizzes_admin.add_tier(session, quiz_id, name_de, name_en, mn, mx)
    if _is_inline(request):
        t = quizzes_admin.get_tiers(session, quiz_id)[-1]
        return _fragment(request, session, quiz_id, "admin/_tier_card.html", {"t": t})
    return _redirect_back(request, quiz_id)


@router.post("/tiers/{tier_id}")
def update_tier(
    tier_id: int,
    request: Request,
    quiz_id: int = Form(...),
    name_de: str = Form(""),
    name_en: str = Form(""),
    min_score: str = Form("0"),
    max_score: str = Form("100"),
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
    try:
        mn, mx = _parse_int(min_score), _parse_int(max_score)
    except ValueError:
        return _invalid(request, quiz_id, "Min/Max müssen ganze Zahlen sein.")
    if mn > mx:
        return _invalid(request, quiz_id, "Min darf nicht größer als Max sein.")
    quizzes_admin.update_tier(
        session,
        tier_id,
        name_de=name_de,
        name_en=name_en,
        min_score=mn,
        max_score=mx,
        headline_de=headline_de,
        headline_en=headline_en,
        body_de=body_de,
        body_en=body_en,
        cta_label_de=cta_label_de,
        cta_label_en=cta_label_en,
        cta_url=cta_url,
        position=position,
    )
    if _is_inline(request):
        t = quizzes_admin.get_tier(session, tier_id)
        if t is None:
            return Response(status_code=404)
        return _fragment(request, session, quiz_id, "admin/_tier_card.html", {"t": t})
    return _redirect_back(request, quiz_id)


@router.post("/tiers/{tier_id}/delete")
def delete_tier(
    tier_id: int,
    request: Request,
    quiz_id: int = Form(...),
    session: Session = Depends(get_session),
):
    quizzes_admin.delete_tier(session, tier_id)
    return _saved(request, quiz_id)


# --- Leads -----------------------------------------------------------------
@router.get("/quizzes/{quiz_id}/leads", response_class=HTMLResponse)
def leads(quiz_id: int, request: Request, session: Session = Depends(get_session)):
    quiz = quizzes_admin.get_quiz(session, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")
    return templates.TemplateResponse(
        request,
        "admin/leads.html",
        {
            "quiz": quiz,
            "active": "leads",
            "leads": submissions_service.list_submissions(session, quiz_id),
        },
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
