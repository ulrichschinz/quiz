"""interfaces.lead_mail — render a committed lead's mails and hand them to the pipeline.

The ONE place where a submission's customer + team e-mails are rendered (the
interface layer owns templating; the pipeline is a dumb transmitter). Used by
both the public submit (`api.router`) and the admin "Erneut senden" retry
(`web.admin`), so the two paths can never drift apart again (SEC-010).

Everything is derived from the stored submission plus the quiz *it belongs to*
— the caller passes the quiz loaded by ``submission.quiz_id`` (REV-003), never
one chosen independently.

Rendering is defensive (SEC-011): the admin-edited subject/body templates are
formatted with the whitelisted placeholders only; a broken template (e.g. one
stored before save-time validation existed) is logged and replaced by a neutral
fallback text — it never raises into the visitor's request.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domains.quizzes import service as quizzes_service
from app.domains.quizzes.schemas import BODY_PLACEHOLDERS, SUBJECT_PLACEHOLDERS
from app.domains.submissions import pipeline
from app.domains.submissions import service as submissions_service
from app.shared import emails
from app.shared.validation import format_template

log = get_logger("interfaces.lead_mail")


def result_url(public_id: str) -> str:
    host = get_settings().app_host
    return f"https://{host}/r/{public_id}" if host else f"/r/{public_id}"


def logo_url() -> str:
    host = get_settings().app_host
    return f"https://{host}{emails.LOGO_PATH}" if host else emails.LOGO_PATH


def _fallback_subject(lang: str, score: int) -> str:
    if lang == "en":
        return f"Your result: {score}/100"
    return f"Ihr Ergebnis: {score}/100"


def _fallback_body(lang: str, *, name: str, score: int, tier: str, url: str) -> str:
    tier_txt = f" ({tier})" if tier else ""
    if lang == "en":
        greeting = f"Hi {name}," if name else "Hello,"
        return f"{greeting}\n\nyour score is {score}/100{tier_txt}.\nFull evaluation: {url}"
    greeting = f"Hallo {name}," if name else "Hallo,"
    return f"{greeting}\n\nIhr Score liegt bei {score}/100{tier_txt}.\nAuswertung: {url}"


def render_template(
    template: str, allowed: frozenset[str], values: dict[str, Any], fallback: str, *, what: str
) -> str:
    """Format an admin template; on any problem log it and return `fallback`."""
    if not template.strip():
        return fallback
    try:
        return format_template(template, allowed, values)
    except Exception as exc:  # never break the lead path on a bad template
        log.warning("Invalid %s template, using fallback text: %s", what, exc)
        return fallback


def dispatch_lead(
    session: Session,
    submission: Any,
    quiz: Any,
    *,
    crm: bool = True,
    email: bool = True,
    only_recipients: set[str] | None = None,
) -> None:
    """Render the mails for `submission` (of `quiz`) and run the selected legs."""
    lang = submission.lang
    score = submission.overall_score
    url = result_url(submission.public_id)
    answers = submissions_service.stored_answers(submission)
    dimension_scores = submissions_service.stored_dimension_scores(submission)

    email_cfg = quizzes_service.get_result_email_config(session, quiz, lang)
    result_view = quizzes_service.get_result_view(
        session, quiz.slug, submission.tier_id, dimension_scores, lang
    )

    values = {
        "name": submission.name or "",
        "score": score,
        "tier": submission.tier_name or "",
        "url": url,
    }
    customer_subject = render_template(
        email_cfg.subject_template,
        SUBJECT_PLACEHOLDERS,
        values,
        _fallback_subject(lang, score),
        what="subject",
    )
    customer_text = render_template(
        email_cfg.body_template,
        BODY_PLACEHOLDERS,
        values,
        _fallback_body(lang, name=values["name"], score=score, tier=values["tier"], url=url),
        what="body",
    )
    customer_html = emails.render_customer_email(
        lang=lang,
        intro_text=customer_text,
        overall_score=score,
        tier_name=result_view.tier_name,
        tier_headline=result_view.tier_headline,
        tier_body=result_view.tier_body,
        dimensions=[(d.name, d.score) for d in result_view.dimensions],
        show_breakdown=result_view.show_breakdown,
        cta_label=result_view.cta_label,
        cta_url=result_view.cta_url,
        result_url=url,
        logo_url=logo_url(),
    )

    # Internal team notification: full answer breakdown so the team can prep.
    breakdown = quizzes_service.get_answer_breakdown(session, quiz, answers, dimension_scores, lang)
    team_html, team_text = emails.render_team_email(
        overall_score=score,
        tier_name=submission.tier_name,
        breakdown=breakdown,
        lead_name=submission.name,
        lead_email=submission.email,
        lead_company=submission.company,
        consent=submission.consent,
        result_url=url,
        logo_url=logo_url(),
    )

    pipeline.dispatch(
        session,
        submission,
        customer_subject=customer_subject,
        customer_text=customer_text,
        customer_html=customer_html,
        team_subject=(
            f"Neuer Lead: {score}/100 — {submission.company or submission.name or submission.email}"
        ),
        team_text=team_text,
        team_html=team_html,
        notify_emails=email_cfg.notify_emails,
        result_url=url,
        crm=crm,
        email=email,
        only_recipients=only_recipients,
    )
