"""e2e: admin lead operations — retry (SEC-010/REV-003), CSV export (SEC-004),
result-email template validation on save (SEC-011)."""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager

import pytest
from sqlmodel import Session, select

from app.domains.quizzes.models import Quiz, QuizResultConfig
from app.domains.submissions import pipeline
from app.domains.submissions.models import Submission
from tests.conftest import ADMIN_PW


def _login(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    assert client.post("/login", data={"password": ADMIN_PW}, follow_redirects=False).status_code == 303


def _submit(client, **extra) -> str:
    payload = client.get("/api/quiz/test-quiz").json()
    answers = {str(q["id"]): q["options"][1]["id"] for q in payload["questions"]}
    body = {"answers": answers, "email": "lead@example.com", "lang": "de", **extra}
    r = client.post("/api/quiz/test-quiz/submit", json=body)
    assert r.status_code == 200
    return r.json()["public_id"]


def _sub(engine, public_id: str) -> Submission:
    with Session(engine) as s:
        return s.exec(select(Submission).where(Submission.public_id == public_id)).one()


def _quiz_id(engine) -> int:
    with Session(engine) as s:
        return s.exec(select(Quiz).where(Quiz.slug == "test-quiz")).one().id


@pytest.fixture
def smtp(monkeypatch):
    """Email leg on; `smtp.fail` = recipients refused; `smtp.sent` = delivered."""

    class Sink:
        fail: set[str] = set()
        sent: list = []
        down = False

    def fake_send(settings, messages):
        if Sink.down:
            raise OSError("relay down")
        failures = {}
        for m in messages:
            if m[0] in Sink.fail:
                failures[m[0]] = "550 refused"
            else:
                Sink.sent.append(m)
        return failures

    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setattr(pipeline, "_smtp_send", fake_send)
    Sink.fail, Sink.sent, Sink.down = set(), [], False
    return Sink


# --- SEC-010 / REV-003 -------------------------------------------------------


@pytest.mark.e2e
def test_retry_resends_failed_mail(client, seeded, engine, smtp, monkeypatch):
    smtp.down = True
    public_id = _submit(client, name="Dana")
    sub = _sub(engine, public_id)
    assert sub.email_sent is False and "relay down" in sub.email_error

    smtp.down = False
    _login(client, monkeypatch)
    r = client.post(
        f"/admin/submissions/{sub.id}/retry", data={"quiz_id": sub.quiz_id}, follow_redirects=False
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/admin/quizzes/{sub.quiz_id}/leads"
    after = _sub(engine, public_id)
    assert after.email_sent is True and after.email_error is None
    assert sorted(m[0] for m in smtp.sent) == ["lead@example.com", "team@example.com"]
    customer = next(m for m in smtp.sent if m[0] == "lead@example.com")
    assert customer[1] == "Score 100" and "Hallo Dana" in customer[2]  # the quiz's own template

    # Idempotent: everything delivered => a second retry sends nothing.
    smtp.sent.clear()
    r = client.post(
        f"/admin/submissions/{sub.id}/retry", data={"quiz_id": sub.quiz_id}, follow_redirects=False
    )
    assert r.status_code == 303 and smtp.sent == []


@pytest.mark.e2e
def test_retry_only_resends_refused_recipients(client, seeded, engine, smtp, monkeypatch):
    smtp.fail = {"team@example.com"}
    public_id = _submit(client)
    sub = _sub(engine, public_id)
    assert sub.email_sent is False  # REV-001: partial refusal is not success
    assert [m[0] for m in smtp.sent] == ["lead@example.com"]

    smtp.fail, smtp.sent[:] = set(), []
    _login(client, monkeypatch)
    client.post(f"/admin/submissions/{sub.id}/retry", data={"quiz_id": sub.quiz_id})
    assert [m[0] for m in smtp.sent] == ["team@example.com"]  # lead not mailed twice
    assert _sub(engine, public_id).email_sent is True


@pytest.mark.e2e
def test_retry_with_mismatched_quiz_id_is_refused(client, seeded, engine, smtp, monkeypatch):
    smtp.down = True
    sub = _sub(engine, _submit(client))
    smtp.down = False
    _login(client, monkeypatch)
    with Session(engine) as s:
        other = Quiz(slug="other", title_de="O", title_en="O")
        s.add(other)
        s.commit()
        s.refresh(other)
        s.add(QuizResultConfig(quiz_id=other.id, notify_emails="attacker@example.com"))
        s.commit()
        other_id = other.id
    r = client.post(
        f"/admin/submissions/{sub.id}/retry", data={"quiz_id": other_id}, follow_redirects=False
    )
    assert r.status_code == 404
    assert smtp.sent == []
    assert client.post("/admin/submissions/99999/retry", data={"quiz_id": sub.quiz_id}).status_code == 404


@pytest.mark.e2e
def test_parallel_retry_is_a_noop(client, seeded, engine, smtp, monkeypatch):
    smtp.down = True
    sub = _sub(engine, _submit(client))
    smtp.down = False
    _login(client, monkeypatch)
    with pipeline.exclusive(sub.id) as acquired:  # another retry is in flight
        assert acquired
        r = client.post(
            f"/admin/submissions/{sub.id}/retry", data={"quiz_id": sub.quiz_id}, follow_redirects=False
        )
    assert r.status_code == 303 and smtp.sent == []


@pytest.mark.e2e
def test_retry_rechecks_state_after_acquiring_the_lock(client, seeded, engine, smtp, monkeypatch):
    """REV-003 follow-up: retry A delivers and releases the lock just before
    retry B (which read the row earlier) gets it — B must not send again."""
    smtp.down = True
    sub = _sub(engine, _submit(client))
    smtp.down = False
    _login(client, monkeypatch)
    real_exclusive = pipeline.exclusive

    @contextmanager
    def exclusive_after_other_retry(submission_id):
        with Session(engine) as s:  # retry A finished in between
            row = s.get(Submission, submission_id)
            row.email_sent, row.email_error = True, None
            s.add(row)
            s.commit()
        with real_exclusive(submission_id) as acquired:
            yield acquired

    monkeypatch.setattr(pipeline, "exclusive", exclusive_after_other_retry)
    r = client.post(
        f"/admin/submissions/{sub.id}/retry", data={"quiz_id": sub.quiz_id}, follow_redirects=False
    )
    assert r.status_code == 303 and smtp.sent == []


# --- SEC-004 -----------------------------------------------------------------


@pytest.mark.e2e
def test_csv_export_neutralises_formulas(client, seeded, engine, monkeypatch):
    _submit(client, email="=cmd@example.com", name="=1+1", company="+SUM(A1)")
    _submit(client, email="b@example.com", name="@evil", company="-2")
    _submit(client, email="c@example.com", name="Dana", company="ACME")
    _login(client, monkeypatch)
    r = client.get(f"/admin/quizzes/{_quiz_id(engine)}/leads.csv")
    assert r.status_code == 200
    rows = {row["name"]: row for row in csv.DictReader(io.StringIO(r.text))}
    assert rows["'=1+1"]["email"] == "'=cmd@example.com"
    assert rows["'=1+1"]["company"] == "'+SUM(A1)"
    assert rows["'@evil"]["company"] == "'-2"
    assert rows["Dana"]["company"] == "ACME"  # harmless cells untouched
    for row in rows.values():
        for col in ("email", "name", "company", "tier"):
            assert not row[col].startswith(("=", "+", "-", "@", "\t", "\r"))


# --- SEC-011: save-time template validation -----------------------------------


def _result_form(**overrides) -> dict:
    form = {
        "intro_de": "Ergebnis",
        "intro_en": "Result",
        "email_subject_de": "Score {score}",
        "email_subject_en": "Score {score}",
        "email_body_de": "Hallo {name}, {score} {tier} {url}",
        "email_body_en": "Hi {name}, {score} {tier} {url}",
        "notify_emails": "team@example.com",
    }
    form.update(overrides)
    return form


@pytest.mark.e2e
@pytest.mark.parametrize(
    "field,value",
    [
        ("email_body_de", "Hallo {vorname}"),
        ("email_body_en", "{name.__class__.__init__}"),
        ("email_subject_de", "{score[0]}"),
        ("email_subject_en", "10 }"),
    ],
)
def test_invalid_template_is_rejected_on_save(client, seeded, engine, monkeypatch, field, value):
    _login(client, monkeypatch)
    qid = _quiz_id(engine)
    r = client.post(
        f"/admin/quizzes/{qid}/result", data=_result_form(**{field: value}), headers={"X-Inline": "1"}
    )
    assert r.status_code == 422
    assert "Platzhalter" in r.text or "Klammern" in r.text
    with Session(engine) as s:
        cfg = s.exec(select(QuizResultConfig).where(QuizResultConfig.quiz_id == qid)).one()
        assert getattr(cfg, field) != value  # nothing saved
    # The public submit keeps working.
    _submit(client)


@pytest.mark.e2e
def test_valid_template_is_saved(client, seeded, engine, monkeypatch):
    _login(client, monkeypatch)
    qid = _quiz_id(engine)
    r = client.post(
        f"/admin/quizzes/{qid}/result",
        data=_result_form(email_body_de="Hallo {name}! {{nicht ersetzt}}"),
        headers={"X-Inline": "1"},
    )
    assert r.status_code == 204


@pytest.mark.e2e
@pytest.mark.parametrize(
    "value", ["a@x.de\nBcc: evil@y.de", "a@x.de; b@y.de", "\"a,b\"@x.de", "not-an-address"]
)
def test_invalid_notify_emails_rejected_on_save(client, seeded, engine, monkeypatch, value):
    _login(client, monkeypatch)
    qid = _quiz_id(engine)
    r = client.post(
        f"/admin/quizzes/{qid}/result", data=_result_form(notify_emails=value), headers={"X-Inline": "1"}
    )
    assert r.status_code == 422
    with Session(engine) as s:
        cfg = s.exec(select(QuizResultConfig).where(QuizResultConfig.quiz_id == qid)).one()
        assert cfg.notify_emails != value


@pytest.mark.e2e
def test_notify_emails_normalised_on_save(client, seeded, engine, monkeypatch):
    _login(client, monkeypatch)
    qid = _quiz_id(engine)
    r = client.post(
        f"/admin/quizzes/{qid}/result",
        data=_result_form(notify_emails=" Team@Example.COM , ops@example.com,team@example.com "),
        headers={"X-Inline": "1"},
    )
    assert r.status_code == 204
    with Session(engine) as s:
        cfg = s.exec(select(QuizResultConfig).where(QuizResultConfig.quiz_id == qid)).one()
        assert cfg.notify_emails == "Team@example.com, ops@example.com"
