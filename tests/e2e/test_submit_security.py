"""e2e: public submit abuse controls (SEC-002, SEC-003, SEC-011, SEC-017)."""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session, select

from app.domains.quizzes.models import QuizResultConfig
from app.domains.submissions import pipeline
from app.domains.submissions.models import Submission

URL = "/api/quiz/test-quiz/submit"


def _answers(client) -> dict[str, int]:
    payload = client.get("/api/quiz/test-quiz").json()
    return {str(q["id"]): q["options"][1]["id"] for q in payload["questions"]}


def _body(client, **overrides) -> dict:
    body = {"answers": _answers(client), "email": "lead@example.com", "lang": "de"}
    body.update(overrides)
    return body


@pytest.fixture
def smtp_capture(monkeypatch) -> list:
    """Enable the email leg and capture what would be handed to SMTP."""
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    sent: list = []
    monkeypatch.setattr(pipeline, "_smtp_send", lambda settings, messages: sent.extend(messages))
    return sent


def _count(engine) -> int:
    with Session(engine) as s:
        return len(s.exec(select(Submission)).all())


# --- SEC-002: exactly one recipient, bounded free text ----------------------


@pytest.mark.e2e
@pytest.mark.parametrize(
    "email",
    ["a@x.de, b@y.de", "a@x.de;b@y.de", "a@x.de\r\nBcc: c@z.de", "", "not-an-email"],
)
def test_submit_rejects_anything_but_one_address(client, seeded, engine, smtp_capture, email):
    r = client.post(URL, json=_body(client, email=email))
    assert r.status_code == 422
    assert _count(engine) == 0 and smtp_capture == []


@pytest.mark.e2e
@pytest.mark.parametrize("field,value", [("name", "x" * 201), ("company", "ACME\nVisit evil.test")])
def test_submit_rejects_long_or_multiline_text(client, seeded, engine, field, value):
    assert client.post(URL, json=_body(client, **{field: value})).status_code == 422
    assert _count(engine) == 0


@pytest.mark.e2e
def test_customer_mail_has_exactly_one_recipient(client, seeded, smtp_capture):
    r = client.post(URL, json=_body(client, email="Lead@Example.COM", name="Dana"))
    assert r.status_code == 200
    recipients = [m[0] for m in smtp_capture]
    assert recipients == ["Lead@example.com", "team@example.com"]


# --- SEC-003 / SEC-017: answers must be this quiz's complete sheet -----------


@pytest.mark.e2e
def test_unknown_question_or_option_is_422(client, seeded, engine):
    answers = _answers(client)
    unknown_q = dict(answers, **{"999999": 1})
    assert client.post(URL, json=_body(client, answers=unknown_q)).status_code == 422
    qid = next(iter(answers))
    wrong_opt = dict(answers, **{qid: 999999})
    assert client.post(URL, json=_body(client, answers=wrong_opt)).status_code == 422
    other_q_opt = dict(answers)
    a, b = list(answers)
    other_q_opt[a] = answers[b]  # an option that belongs to the other question
    assert client.post(URL, json=_body(client, answers=other_q_opt)).status_code == 422
    assert _count(engine) == 0


@pytest.mark.e2e
def test_missing_required_question_is_422(client, seeded, engine):
    answers = _answers(client)
    partial = dict([next(iter(answers.items()))])
    r = client.post(URL, json=_body(client, answers=partial))
    assert r.status_code == 422
    assert "unanswered" in json.dumps(r.json())
    assert client.post(URL, json=_body(client, answers={})).status_code == 422
    assert _count(engine) == 0


@pytest.mark.e2e
def test_rate_limit_per_ip(client, seeded, monkeypatch):
    monkeypatch.setenv("SUBMIT_DEDUP_WINDOW_SECONDS", "0")
    body = _body(client)
    for _ in range(10):
        assert client.post(URL, json=body).status_code == 200
    r = client.post(URL, json=body)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1


@pytest.mark.e2e
def test_hourly_rate_limit(client, seeded, monkeypatch):
    monkeypatch.setenv("SUBMIT_MAX_PER_MINUTE", "0")
    monkeypatch.setenv("SUBMIT_MAX_PER_HOUR", "3")
    monkeypatch.setenv("SUBMIT_DEDUP_WINDOW_SECONDS", "0")
    body = _body(client)
    assert [client.post(URL, json=body).status_code for _ in range(4)] == [200, 200, 200, 429]


@pytest.mark.e2e
def test_oversized_body_is_413(client, seeded, engine):
    big = _body(client, name="x" * 70_000)
    assert client.post(URL, json=big).status_code == 413

    # Chunked (no Content-Length): cut off while streaming.
    raw = json.dumps(big).encode()

    def chunks():
        for i in range(0, len(raw), 8192):
            yield raw[i : i + 8192]

    r = client.post(URL, content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert _count(engine) == 0


@pytest.mark.e2e
def test_duplicate_within_window_does_not_resend(client, seeded, engine, smtp_capture):
    body = _body(client)
    first = client.post(URL, json=body)
    assert first.status_code == 200
    assert len(smtp_capture) == 2  # customer + team
    second = client.post(URL, json=_body(client, email="LEAD@example.com"))
    assert second.status_code == 200
    assert client.get(second.json()["redirect"]).status_code == 200  # still gets a result
    assert len(smtp_capture) == 2  # no second round of mails
    with Session(engine) as s:
        dup = s.exec(select(Submission).where(Submission.public_id == second.json()["public_id"])).one()
        assert dup.email_sent is False and dup.email_error == pipeline.DUPLICATE_NOTE


# --- SEC-011: a broken stored template never fails the visitor ---------------


@pytest.mark.e2e
@pytest.mark.parametrize("subject,body", [("{vorname}", "10 }"), ("{score.__class__}", "{name[0]}")])
def test_broken_stored_template_still_200_with_fallback(
    client, seeded, engine, smtp_capture, subject, body
):
    with Session(engine) as s:
        cfg = s.exec(select(QuizResultConfig)).one()
        cfg.email_subject_de, cfg.email_body_de = subject, body
        s.add(cfg)
        s.commit()
    r = client.post(URL, json=_body(client, name="Dana"))
    assert r.status_code == 200
    customer = next(m for m in smtp_capture if m[0] == "lead@example.com")
    assert customer[1] == "Ihr Ergebnis: 100/100"
    assert "Dana" in customer[2] and "/r/" in customer[2]


@pytest.mark.e2e
def test_fanout_crash_after_commit_is_not_a_500(client, seeded, engine, monkeypatch):
    from app.interfaces import lead_mail

    def boom(*a, **k):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(lead_mail.emails, "render_customer_email", boom)
    r = client.post(URL, json=_body(client))
    assert r.status_code == 200
    assert _count(engine) == 1
