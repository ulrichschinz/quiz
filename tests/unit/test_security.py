"""Unit tests for the fail-closed settings and the auth helpers (security audit).

SEC-001 (SECRET_KEY), SEC-005 (cookie settings defaults), SEC-007 (password
minimum + login throttle), SEC-006 (session registry), SEC-013 (unicode
compare), SEC-016 (docs default off).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import (
    AdminSessionRegistry,
    LoginThrottle,
    normalize_client_ip,
    password_fingerprint,
    verify_admin_password,
)

STRONG_KEY = "k" * 48
REPO = Path(__file__).resolve().parents[2]


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- SEC-001: SECRET_KEY fails closed ----------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "dev-secret-change-me",
        "change-me-generate-a-random-64-char-hex",
        "change-me-but-this-is-definitely-longer-than-32-chars",
        "CHANGE-ME-uppercase-placeholder-also-longer-than-32",
        "too-short-but-random-Xy7",
    ],
)
def test_weak_or_placeholder_secret_key_is_rejected(monkeypatch, value) -> None:
    monkeypatch.setenv("SECRET_KEY", value)
    with pytest.raises(ValidationError) as exc:
        Settings()
    msg = str(exc.value)
    assert "SECRET_KEY" in msg
    if value.strip():
        assert value not in msg  # never echo the secret


def test_missing_secret_key_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="SECRET_KEY is not set"):
        Settings()


def test_strong_secret_key_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", STRONG_KEY)
    assert Settings().secret_key == STRONG_KEY


def test_app_refuses_to_start_without_secret_key() -> None:
    env = {k: v for k, v in os.environ.items() if k != "SECRET_KEY"}
    env["SECRET_KEY"] = "dev-secret-change-me"
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "SECRET_KEY" in proc.stderr
    assert "dev-secret-change-me" not in proc.stderr


# --- SEC-007: ADMIN_PASSWORD minimum strength --------------------------------


@pytest.mark.parametrize("pw", ["secret", "change-me", "elevenchars", "change-me-please-123"])
def test_short_or_placeholder_admin_password_disables_admin_only(monkeypatch, caplog, pw) -> None:
    """Review follow-up: a weak ADMIN_PASSWORD must not crash-loop the whole app
    (public funnel included). It is treated as unset — admin login disabled — and
    reported in the log without the value itself."""
    import app.core.config as config_mod

    monkeypatch.setattr(config_mod, "_weak_admin_password_reported", False)
    monkeypatch.setenv("ADMIN_PASSWORD", pw)
    with caplog.at_level("ERROR", logger="quiz.core.config"):
        settings = Settings()  # must not raise
    assert settings.admin_password is None
    assert verify_admin_password(pw, settings.admin_password) is False
    assert "ADMIN_PASSWORD" in caplog.text and pw not in caplog.text


@pytest.mark.parametrize("pw", ["", "twelve-chars"])
def test_empty_or_long_enough_admin_password_is_accepted(monkeypatch, pw) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", pw)
    assert Settings().admin_password == pw


def test_login_throttle_sliding_window() -> None:
    clock = _Clock()
    t = LoginThrottle(clock=clock)
    for _ in range(9):
        t.record_failure("1.2.3.4", 900)
        clock.now += 1
    assert t.retry_after("1.2.3.4", 10, 900) == 0
    t.record_failure("1.2.3.4", 900)
    wait = t.retry_after("1.2.3.4", 10, 900)
    assert 0 < wait <= 900
    assert t.retry_after("5.6.7.8", 10, 900) == 0  # other IPs unaffected
    # The oldest failure slides out of the window -> unblocked again.
    clock.now += wait
    assert t.retry_after("1.2.3.4", 10, 900) == 0
    t.reset("1.2.3.4")
    assert t.retry_after("1.2.3.4", 1, 900) == 0


def test_login_throttle_bounds_tracked_keys() -> None:
    t = LoginThrottle(max_keys=3, clock=_Clock())
    for i in range(10):
        t.record_failure(f"10.0.0.{i}", 900)
    assert len(t._failures) <= 3


# --- SEC-006: server-side session registry -----------------------------------


def test_session_registry_issue_revoke_expire() -> None:
    clock = _Clock()
    reg = AdminSessionRegistry(clock=clock)
    sid = reg.issue(ttl_seconds=60)
    assert reg.is_active(sid)
    assert not reg.is_active("forged")
    reg.revoke(sid)
    assert not reg.is_active(sid)

    sid2 = reg.issue(ttl_seconds=60)
    clock.now += 61
    assert not reg.is_active(sid2)  # absolute lifetime enforced server-side


def test_password_fingerprint_changes_with_password_and_key() -> None:
    fp = password_fingerprint("correct-horse-battery", STRONG_KEY)
    assert fp and len(fp) == 32
    assert fp == password_fingerprint("correct-horse-battery", STRONG_KEY)
    assert fp != password_fingerprint("another-password-x", STRONG_KEY)
    assert fp != password_fingerprint("correct-horse-battery", "j" * 48)
    assert password_fingerprint(None, STRONG_KEY) is None


# --- SEC-013: unicode-safe constant-time compare -----------------------------


def test_verify_admin_password_handles_non_ascii() -> None:
    assert verify_admin_password("ä", "ascii-only-password") is False
    assert verify_admin_password("Sömmer-Passwört", "Sömmer-Passwört") is True
    assert verify_admin_password("Sommer-Passwort", "Sömmer-Passwört") is False
    assert verify_admin_password("anything", None) is False


# --- SEC-005 / SEC-016: secure defaults ---------------------------------------


def test_secure_defaults(monkeypatch) -> None:
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    s = Settings()
    assert s.session_https_only is True
    assert s.session_max_age == 8 * 60 * 60
    assert s.enable_api_docs is False
    assert s.login_max_failures == 10
    assert s.login_window_seconds == 15 * 60


# --- SEC-003/007 review follow-up: throttle key normalisation -----------------


@pytest.mark.parametrize(
    "host,expected",
    [
        ("203.0.113.7", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),  # IPv4-mapped => same bucket as IPv4
        ("2001:db8::1", "2001:db8::/64"),
        ("2001:db8:0:0:ffff:ffff:ffff:ffff", "2001:db8::/64"),
        ("2001:db8:0:1::1", "2001:db8:0:1::/64"),
        ("testclient", "testclient"),  # unparsable => verbatim
    ],
)
def test_client_ip_normalisation(host, expected) -> None:
    assert normalize_client_ip(host) == expected
