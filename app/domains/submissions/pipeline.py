"""Submissions domain — the lead pipeline (fan-out, fault-isolated).

The local Submission row is already committed before this runs (it is the
source of truth). `dispatch` then fans the lead out to two more destinations,
each isolated so one failing never blocks the others or the visitor's redirect:

1. vibe CRM   — `POST {CRM_INGEST_URL}` with `X-API-Key` (CrmLead DTO).
2. SMTP email — a result email to the lead + a notification to the team.

Each leg is skipped cleanly when its env config is absent (local dev), and a
failure is recorded on the submission (`crm_error` / `email_error`) for the
admin retry action rather than raised.

SMTP (SEC-009): STARTTLS and SMTPS (port 465) use
`ssl.create_default_context()` — certificate chain AND hostname are verified, a
MITM certificate aborts before `login`. Every message is sent and evaluated on
its own (REV-001): `email_sent` is only True when the relay accepted every
message; otherwise `email_error` lists the refused recipients (see
`failed_email_recipients`) so a retry re-sends only those.
"""

from __future__ import annotations

import json
import smtplib
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
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
_SMTPS_PORT = 465
_ERROR_MAX = 500
_PARTIAL_PREFIX = "partial: "
DUPLICATE_NOTE = "Duplikat (gleiche E-Mail kurz zuvor) - nicht erneut versendet"

# (to, subject, text, html|None) — html rides as a multipart alternative.
Message = tuple[str, str, str, str | None]

_inflight_lock = threading.Lock()
_inflight: set[int] = set()


@contextmanager
def exclusive(submission_id: int) -> Iterator[bool]:
    """Yield True if no other dispatch for this submission runs in this process.

    Guards the admin retry against a double click / parallel retries sending the
    same lead twice (REV-003). Single-process assumption, like the auth registries.
    """
    with _inflight_lock:
        acquired = submission_id not in _inflight
        if acquired:
            _inflight.add(submission_id)
    try:
        yield acquired
    finally:
        if acquired:
            with _inflight_lock:
                _inflight.discard(submission_id)


def dispatch(
    session: Session,
    submission: Submission,
    *,
    customer_subject: str,
    customer_text: str,
    team_subject: str,
    team_text: str,
    notify_emails: str,
    result_url: str,
    customer_html: str | None = None,
    team_html: str | None = None,
    crm: bool = True,
    email: bool = True,
    only_recipients: set[str] | None = None,
) -> None:
    """Fan the committed lead out to the CRM + email destinations.

    Subjects/texts come in already rendered (the interface layer owns
    templating); the `*_html` bodies, when present, ride along as the HTML
    alternative so recipients see the branded versions. `crm` / `email` select
    the legs (a retry only repeats failed ones); `only_recipients` limits the
    email leg to those addresses (re-send after a partial SMTP refusal).
    """
    if crm:
        _push_to_crm(session, submission, result_url)
    if not email:
        return
    _send_emails(
        session,
        submission,
        customer_subject=customer_subject,
        customer_text=customer_text,
        customer_html=customer_html,
        team_subject=team_subject,
        team_text=team_text,
        team_html=team_html,
        notify_emails=notify_emails,
        only_recipients=only_recipients,
    )


def mark_duplicate(session: Session, submission: Submission) -> None:
    """Record that this lead was intentionally NOT fanned out (dedup window)."""
    submission.crm_error = DUPLICATE_NOTE
    submission.email_error = DUPLICATE_NOTE
    session.add(submission)
    session.commit()


def failed_email_recipients(submission: Submission) -> set[str] | None:
    """Recipients refused in the last partial email failure; None == resend all."""
    err = submission.email_error or ""
    if not err.startswith(_PARTIAL_PREFIX):
        return None
    try:
        data = json.loads(err[len(_PARTIAL_PREFIX) :])
    except ValueError:
        return None
    if not isinstance(data, dict) or not data:
        return None
    return {str(k) for k in data}


def _format_partial(failures: dict[str, str]) -> str:
    per = max(40, (_ERROR_MAX - len(_PARTIAL_PREFIX)) // max(1, len(failures)) - 60)
    text = _PARTIAL_PREFIX + json.dumps(
        {to: reason[:per] for to, reason in failures.items()}, ensure_ascii=False
    )
    if len(text) > _ERROR_MAX:  # many recipients: keep it parseable, drop reasons
        text = _PARTIAL_PREFIX + json.dumps(dict.fromkeys(failures, ""), ensure_ascii=False)
    return text[:_ERROR_MAX]


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
    *,
    customer_subject: str,
    customer_text: str,
    customer_html: str | None,
    team_subject: str,
    team_text: str,
    team_html: str | None,
    notify_emails: str,
    only_recipients: set[str] | None = None,
) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        return  # leg disabled (local dev)

    messages: list[Message] = []
    if submission.email:
        messages.append((submission.email, customer_subject, customer_text, customer_html))

    for addr in (e.strip() for e in notify_emails.split(",") if e.strip()):
        messages.append((addr, team_subject, team_text, team_html))

    if only_recipients is not None:
        messages = [m for m in messages if m[0] in only_recipients]

    try:
        failures = _smtp_send(settings, messages) or {}
        if failures:
            submission.email_sent = False
            submission.email_error = _format_partial(failures)
            log.warning(
                "Email partially refused for submission %s: %s",
                submission.public_id,
                sorted(failures),
            )
        else:
            submission.email_sent = True
            submission.email_error = None
    except Exception as exc:
        submission.email_sent = False
        submission.email_error = str(exc)[:_ERROR_MAX]
        log.warning("Email send failed for submission %s: %s", submission.public_id, exc)
    session.add(submission)
    session.commit()


def _connect(settings: Settings) -> smtplib.SMTP:
    """Open a verified TLS SMTP connection (SEC-009). Port 465 => implicit TLS."""
    context = ssl.create_default_context()
    if settings.smtp_port == _SMTPS_PORT:
        return smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT, context=context
        )
    server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT)
    try:
        if settings.smtp_starttls:
            server.starttls(context=context)
    except BaseException:
        server.close()
        raise
    return server


def _smtp_send(settings: Settings, messages: list[Message]) -> dict[str, str]:
    """Send each message on one connection; return {recipient: reason} of refusals.

    Connection / TLS / login errors raise (whole leg failed). A refusal of one
    message (RCPT/DATA rejected) is recorded and the remaining messages are
    still attempted (REV-001).
    """
    failures: dict[str, str] = {}
    if not messages:
        return failures
    with _connect(settings) as server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        for i, (to, subject, text, html) in enumerate(messages):
            msg = EmailMessage()
            msg["From"] = settings.smtp_from
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(text)
            if html:
                msg.add_alternative(html, subtype="html")
            try:
                refused = server.send_message(msg, to_addrs=[to])
            except smtplib.SMTPServerDisconnected as exc:
                # Connection gone: this and every remaining message is unsent.
                for rest_to, *_ in messages[i:]:
                    failures[rest_to] = f"disconnected: {exc}"
                break
            except (smtplib.SMTPException, ValueError) as exc:
                failures[to] = str(exc)
                continue
            for addr, (code, reply) in (refused or {}).items():
                failures[addr] = f"{code} {reply.decode('utf-8', 'replace')}"
    return failures
