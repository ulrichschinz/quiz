"""Submissions domain — the lead pipeline (fan-out, fault-isolated).

The local Submission row is already committed before this runs (it is the
source of truth). `dispatch` then fans the lead out to two more destinations,
each isolated so one failing never blocks the others or the visitor's redirect:

1. vibe CRM   — `POST {CRM_INGEST_URL}` with `X-API-Key` (CrmLead DTO).
2. SMTP email — a result email to the lead + a notification to the team.

Each leg is skipped cleanly when its env config is absent (local dev), and a
failure is recorded on the submission (`crm_error` / `email_error`) for the
admin retry action rather than raised.
"""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage

import httpx
from sqlmodel import Session

from app.contracts.crm_lead import CrmLead
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.domains.submissions.models import Submission
from app.shared.clock import utcnow

log = get_logger("submissions.pipeline")

_CRM_TIMEOUT = 5.0
_SMTP_TIMEOUT = 10.0


def dispatch(
    session: Session,
    submission: Submission,
    *,
    email_subject: str,
    email_body: str,
    notify_emails: str,
    result_url: str,
) -> None:
    """Fan the committed lead out to the CRM + email destinations."""
    _push_to_crm(session, submission, result_url)
    _send_emails(session, submission, email_subject, email_body, notify_emails, result_url)


def _push_to_crm(session: Session, submission: Submission, result_url: str) -> None:
    settings = get_settings()
    if not settings.crm_ingest_url:
        return  # leg disabled (local dev)

    lead = CrmLead(
        name=submission.name,
        company=submission.company,
        email=submission.email,
        source="website",
        notes=f"Agentic AI Readiness: {submission.overall_score}/100 ({submission.tier_name})",
        tags=["scorecard", submission.quiz_slug],
        agent_metadata={
            "quiz_slug": submission.quiz_slug,
            "overall_score": submission.overall_score,
            "dimension_scores": json.loads(submission.dimension_scores_json or "{}"),
            "tier": submission.tier_name,
            "result_url": result_url,
            "consent": submission.consent,
        },
    )
    try:
        resp = httpx.post(
            settings.crm_ingest_url,
            json=lead.model_dump(),
            headers={"X-API-Key": settings.crm_api_key},
            timeout=_CRM_TIMEOUT,
        )
        resp.raise_for_status()
        submission.crm_pushed = True
        submission.crm_pushed_at = utcnow()
        submission.crm_error = None
    except Exception as exc:
        submission.crm_error = str(exc)[:500]
        log.warning("CRM push failed for submission %s: %s", submission.public_id, exc)
    session.add(submission)
    session.commit()


def _send_emails(
    session: Session,
    submission: Submission,
    email_subject: str,
    email_body: str,
    notify_emails: str,
    result_url: str,
) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        return  # leg disabled (local dev)

    recipients: list[tuple[str, str, str]] = []
    if submission.email:
        body = email_body.format(
            name=submission.name or "",
            score=submission.overall_score,
            tier=submission.tier_name or "",
            url=result_url,
        )
        subject = email_subject.format(score=submission.overall_score)
        recipients.append((submission.email, subject, body))

    for addr in (e.strip() for e in notify_emails.split(",") if e.strip()):
        note = (
            f"Neuer Scorecard-Lead: {submission.email} ({submission.company})\n"
            f"Score: {submission.overall_score}/100 ({submission.tier_name})\n{result_url}"
        )
        recipients.append((addr, f"Neuer Lead: {submission.overall_score}/100", note))

    try:
        _smtp_send(settings, recipients)
        submission.email_sent = True
        submission.email_error = None
    except Exception as exc:
        submission.email_error = str(exc)[:500]
        log.warning("Email send failed for submission %s: %s", submission.public_id, exc)
    session.add(submission)
    session.commit()


def _smtp_send(settings: Settings, messages: list[tuple[str, str, str]]) -> None:
    if not messages:
        return
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        for to, subject, body in messages:
            msg = EmailMessage()
            msg["From"] = settings.smtp_from
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            server.send_message(msg)
