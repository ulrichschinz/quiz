"""Unit: SMTP transport security (SEC-009) and per-message results (REV-001)."""

from __future__ import annotations

import shutil
import smtplib
import socket
import ssl
import subprocess
import threading

import pytest
from sqlmodel import Session

from app.core.config import get_settings
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


def _send(s: Session, sub, notify: str = "team@example.com", only=None) -> None:
    pipeline._send_emails(
        s,
        sub,
        customer_subject="S",
        customer_text="T",
        customer_html=None,
        team_subject="TS",
        team_text="TT",
        team_html=None,
        notify_emails=notify,
        only_recipients=only,
    )


class FakeSMTP:
    """Records the transport calls; `refuse` = recipients the relay rejects."""

    instances: list[FakeSMTP] = []
    refuse: set[str] = set()

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.context = host, port, context
        self.starttls_context = None
        self.logged_in = False
        self.sent: list[tuple[str, list[str]]] = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self) -> None:
        pass

    def starttls(self, context=None):
        self.starttls_context = context

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, msg, to_addrs=None):
        rcpts = list(to_addrs or [])
        if any(r in FakeSMTP.refuse for r in rcpts):
            raise smtplib.SMTPRecipientsRefused({r: (550, b"no such user") for r in rcpts})
        self.sent.append((msg["To"], rcpts))
        return {}


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.refuse = set()
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setattr(pipeline.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(pipeline.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def _assert_verifying(ctx) -> None:
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_starttls_uses_verifying_context(engine, fake_smtp) -> None:
    with Session(engine) as s:
        sub = _make_submission(s)
        _send(s, sub)
        assert sub.email_sent is True
    (server,) = fake_smtp.instances
    _assert_verifying(server.starttls_context)
    # SEC-002: every message has exactly one envelope recipient.
    assert server.sent == [
        ("lead@example.com", ["lead@example.com"]),
        ("team@example.com", ["team@example.com"]),
    ]


def test_port_465_uses_smtps_with_verifying_context(engine, fake_smtp, monkeypatch) -> None:
    monkeypatch.setenv("SMTP_PORT", "465")
    with Session(engine) as s:
        _send(s, _make_submission(s))
    (server,) = fake_smtp.instances
    assert server.port == 465
    _assert_verifying(server.context)
    assert server.starttls_context is None


def test_partial_refusal_is_not_recorded_as_success(engine, fake_smtp) -> None:
    """REV-001: one refused recipient => email_sent False, refusal recorded."""
    fake_smtp.refuse = {"bad@example.com"}
    with Session(engine) as s:
        sub = _make_submission(s)
        _send(s, sub, notify="team@example.com, bad@example.com")
        assert sub.email_sent is False
        assert "bad@example.com" in (sub.email_error or "")
        assert pipeline.failed_email_recipients(sub) == {"bad@example.com"}
    # The other messages were still attempted and delivered.
    assert [to for to, _ in fake_smtp.instances[0].sent] == ["lead@example.com", "team@example.com"]

    # A follow-up limited to the refused recipient clears the error.
    fake_smtp.refuse = set()
    with Session(engine) as s:
        sub = s.merge(sub)
        _send(s, sub, notify="team@example.com, bad@example.com", only={"bad@example.com"})
        assert sub.email_sent is True and sub.email_error is None
    assert [to for to, _ in fake_smtp.instances[1].sent] == ["bad@example.com"]


def test_connection_failure_resends_everything(engine, monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test")

    def boom(settings, messages):
        raise OSError("connection refused")

    monkeypatch.setattr(pipeline, "_smtp_send", boom)
    with Session(engine) as s:
        sub = _make_submission(s)
        _send(s, sub)
        assert sub.email_sent is False and "connection refused" in (sub.email_error or "")
        assert pipeline.failed_email_recipients(sub) is None  # => retry sends all


# --- real loopback relay with a self-signed certificate (SEC-009) ------------


def _self_signed(tmp_path) -> tuple[str, str]:
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=mitm.invalid", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )  # fmt: skip
    return str(cert), str(key)


def _mitm_relay(cert: str, key: str) -> tuple[int, dict]:
    """Minimal SMTP server: offers STARTTLS, then presents an untrusted cert."""
    state: dict = {"after_tls": []}
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)

    def run() -> None:
        conn, _ = srv.accept()
        f = conn.makefile("rb")
        conn.sendall(b"220 mitm ESMTP\r\n")
        while line := f.readline():
            cmd = line.strip().upper()
            if cmd.startswith(b"EHLO"):
                conn.sendall(b"250-mitm\r\n250 STARTTLS\r\n")
            elif cmd == b"STARTTLS":
                conn.sendall(b"220 go ahead\r\n")
                try:
                    tls = ctx.wrap_socket(conn, server_side=True)
                    state["after_tls"].append(tls.recv(1024))  # AUTH would land here
                except (ssl.SSLError, OSError):
                    pass
                break
            else:
                conn.sendall(b"502 no\r\n")
        conn.close()
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port, state


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI not available")
def test_untrusted_relay_certificate_aborts_before_login(engine, tmp_path, monkeypatch) -> None:
    port, state = _mitm_relay(*_self_signed(tmp_path))
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(port))
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret-password")

    with pytest.raises(ssl.SSLCertVerificationError):
        pipeline._smtp_send(get_settings(), [("lead@example.com", "S", "T", None)])
    assert not any(b"secret" in chunk or b"AUTH" in chunk for chunk in state["after_tls"])

    port, _ = _mitm_relay(*_self_signed(tmp_path))
    monkeypatch.setenv("SMTP_PORT", str(port))
    with Session(engine) as s:
        sub = _make_submission(s)
        _send(s, sub)
        assert sub.email_sent is False
        assert "CERTIFICATE_VERIFY_FAILED" in (sub.email_error or "")


def test_smtp_auth_without_tls_is_refused(engine, fake_smtp, monkeypatch) -> None:
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("SMTP_PORT", "587")
    with Session(engine) as s:
        sub = _make_submission(s)
        _send(s, sub)
        assert sub.email_sent is False
    assert fake_smtp.instances == []  # never even connected
