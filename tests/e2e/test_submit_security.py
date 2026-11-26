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


@pytest.mark.e2e
@pytest.mark.parametrize(
    "first,variant",
    [
        ("victim@example.com", "victim+1@example.com"),
        ("victim@example.com", "Victim+spam@Example.com"),
        ("victim@gmail.com", "v.ic.tim+x@googlemail.com"),
    ],
)
def test_plus_and_dot_variants_count_as_duplicates(
    client, seeded, engine, smtp_capture, first, variant
):
    """Review follow-up: sub-addressing must not bypass the one-mail window."""
    assert client.post(URL, json=_body(client, email=first)).status_code == 200
    assert len(smtp_capture) == 2
    second = client.post(URL, json=_body(client, email=variant))
    assert second.status_code == 200
    assert len(smtp_capture) == 2  # no new customer/team mail
    with Session(engine) as s:
        dup = s.exec(select(Submission).where(Submission.public_id == second.json()["public_id"])).one()
        assert dup.email.split("@")[0] == variant.split("@")[0]  # stored as entered
        assert dup.email_error == pipeline.DUPLICATE_NOTE


@pytest.mark.e2e
def test_other_mailbox_same_domain_is_not_a_duplicate(client, seeded, engine, smtp_capture):
    assert client.post(URL, json=_body(client, email="victim@example.com")).status_code == 200
    assert client.post(URL, json=_body(client, email="victim2@example.com")).status_code == 200
    assert len(smtp_capture) == 4


# --- SEC-003 review follow-up: per-client limit behind a container proxy ------


def _image_forwarded_allow_ips() -> str:
    import re
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    m = re.search(r'^ENV FORWARDED_ALLOW_IPS="([^"]+)"', dockerfile, flags=re.M)
    assert m, "Dockerfile must set a FORWARDED_ALLOW_IPS default"
    return m.group(1)


@pytest.mark.e2e
def test_submit_limit_is_per_forwarded_client_behind_proxy(client, seeded, engine, monkeypatch):
    """With the image's FORWARDED_ALLOW_IPS a proxy container's peer address is
    trusted, so the limit applies to the forwarded client, not the whole site."""
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    from app.main import app

    monkeypatch.setenv("SUBMIT_MAX_PER_MINUTE", "2")
    proxied = ProxyHeadersMiddleware(app, trusted_hosts=_image_forwarded_allow_ips())
    proxy = TestClient(proxied, client=("172.18.0.5", 40000))  # e.g. Traefik's container IP
    body = _body(client)

    def post(ip: str) -> int:
        return proxy.post(URL, json=body, headers={"X-Forwarded-For": ip}).status_code

    assert [post("198.51.100.1") for _ in range(3)] == [200, 200, 429]
    assert post("198.51.100.2") == 200  # another visitor behind the same proxy
    # A spoofed left-most entry does not escape: the proxy-appended one counts.
    assert post("10.9.9.9, 198.51.100.1") == 429


@pytest.mark.e2e
def test_untrusted_proxy_is_reported_once(client, seeded, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    import app.core.security as sec
    from app.main import app

    monkeypatch.setattr(sec, "_untrusted_proxy_reported", False)
    peer = TestClient(app, client=("172.18.0.5", 40000))  # no proxy-headers middleware
    with caplog.at_level("WARNING", logger="quiz.core.security"):
        peer.get("/api/quiz/test-quiz", headers={"X-Forwarded-For": "198.51.100.1"})
        peer.post(URL, json=_body(client), headers={"X-Forwarded-For": "198.51.100.1"})
        peer.post(URL, json=_body(client), headers={"X-Forwarded-For": "198.51.100.1"})
    assert caplog.text.count("FORWARDED_ALLOW_IPS") == 1


# --- REV-002: result links die with their quiz ---------------------------------


@pytest.mark.e2e
def test_result_link_of_unpublished_quiz_is_neutral_404(client, seeded, engine):
    from app.domains.quizzes.models import Quiz, ResultTier

    with Session(engine) as s:
        for tier in s.exec(select(ResultTier)).all():
            tier.body_de = "GEHEIMER-TIERTEXT"
            s.add(tier)
        s.commit()
    r = client.post(URL, json=_body(client))
    link = r.json()["redirect"]
    assert "GEHEIMER-TIERTEXT" in client.get(link).text

    with Session(engine) as s:
        quiz = s.exec(select(Quiz)).one()
        quiz.is_published = False
        s.add(quiz)
        s.commit()
    page = client.get(link)
    assert page.status_code == 404
    assert "GEHEIMER-TIERTEXT" not in page.text
    assert "nicht mehr verfügbar" in page.text


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
