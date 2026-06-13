"""Unit tests for the lead pipeline — graceful skip + fault isolation."""

from __future__ import annotations

from sqlmodel import Session

from app.domains.submissions import pipeline, service


def _make_submission(session: Session):
    return service.create_submission(
        session,
        quiz_id=1,
        quiz_slug="q",
        lang="de",
        answers={1: 2},
        overall_score=72,
        dimension_scores={"alpha": 72},
        tier_id=1,
        tier_name="Builder",
        email="lead@example.com",
        name="Dana",
        company="ACME",
        consent=True,
    )


def test_pipeline_skips_cleanly_when_unconfigured(engine) -> None:
    with Session(engine) as s:
        sub = _make_submission(s)
        pipeline.dispatch(
            s, sub,
            customer_subject="Score 72",
            customer_text="Hi Dana, 72/100",
            customer_html="<p>Hi Dana</p>",
            team_subject="Neuer Lead: 72/100",
            team_text="Lead breakdown",
            team_html="<p>Lead</p>",
            notify_emails="team@example.com",
            result_url="/r/x",
        )
        # No env → both legs skip; nothing flagged, nothing raised.
        assert sub.crm_pushed is False and sub.crm_error is None
        assert sub.email_sent is False and sub.email_error is None


def test_customer_email_carries_html_alternative(engine, monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test")

    captured: list = []
    monkeypatch.setattr(pipeline, "_smtp_send", lambda settings, messages: captured.extend(messages))

    with Session(engine) as s:
        sub = _make_submission(s)
        pipeline._send_emails(
            s, sub,
            customer_subject="Dein Ergebnis: 72/100",
            customer_text="Hallo Dana, plaintext fallback.",
            customer_html="<h1>72/100</h1>",
            team_subject="Neuer Lead: 72/100",
            team_text="Lead breakdown plaintext",
            team_html="<h1>Lead</h1>",
            notify_emails="team@example.com",
        )
        assert sub.email_sent is True and sub.email_error is None

    # Both messages carry their html alternative.
    lead = next(m for m in captured if m[0] == "lead@example.com")
    team = next(m for m in captured if m[0] == "team@example.com")
    assert lead[2] == "Hallo Dana, plaintext fallback." and lead[3] == "<h1>72/100</h1>"
    assert team[2] == "Lead breakdown plaintext" and team[3] == "<h1>Lead</h1>"


def test_crm_push_success_flags_submission(engine, monkeypatch) -> None:
    monkeypatch.setenv("CRM_INGEST_URL", "http://crm.test/api/leads")
    monkeypatch.setenv("CRM_API_KEY", "secret")

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return FakeResp()

    monkeypatch.setattr(pipeline.httpx, "post", fake_post)

    with Session(engine) as s:
        sub = _make_submission(s)
        pipeline._push_to_crm(s, sub, "/r/x")

        assert sub.crm_pushed is True
        assert sub.crm_error is None

    assert captured["url"] == "http://crm.test/api/leads"
    assert captured["headers"]["X-API-Key"] == "secret"
    assert captured["json"]["source"] == "website"
    assert captured["json"]["agent_metadata"]["overall_score"] == 72


def test_crm_push_failure_is_isolated(engine, monkeypatch) -> None:
    monkeypatch.setenv("CRM_INGEST_URL", "http://crm.test/api/leads")

    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(pipeline.httpx, "post", boom)

    with Session(engine) as s:
        sub = _make_submission(s)
        pipeline._push_to_crm(s, sub, "/r/x")

        # The failure is recorded, not raised; the local lead is untouched.
        assert sub.crm_pushed is False
        assert sub.crm_error is not None and "connection refused" in sub.crm_error
        assert sub.overall_score == 72
