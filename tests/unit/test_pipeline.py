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
            email_subject="Score {score}",
            email_body="{name} {score} {tier} {url}",
            notify_emails="team@example.com",
            result_url="/r/x",
        )
        # No env → both legs skip; nothing flagged, nothing raised.
        assert sub.crm_pushed is False and sub.crm_error is None
        assert sub.email_sent is False and sub.email_error is None


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
