"""e2e regression tests for the admin-auth findings of the security audit.

SEC-001 forged cookies, SEC-005 cookie attributes, SEC-006 revocation,
SEC-007 login throttle, SEC-013 unicode passwords, SEC-016 API docs.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator

import itsdangerous
import pytest
from fastapi.testclient import TestClient

from app.core import db as core_db

# >= ADMIN_PASSWORD minimum length (SEC-007).
ADMIN_PW = "correct-horse-battery-staple"


def _forge_session_cookie(secret_key: str, payload: dict) -> str:
    """Sign a Starlette session cookie the way SessionMiddleware does."""
    data = base64.b64encode(json.dumps(payload).encode("utf-8"))
    return itsdangerous.TimestampSigner(secret_key).sign(data).decode("utf-8")


def _fresh_app(monkeypatch, **env: str):
    """Build a separate app instance with the given env (create_app reads Settings)."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(core_db, "create_db", lambda: None)
    from app.main import create_app

    return create_app()


@pytest.fixture
def https_client(monkeypatch) -> Iterator[TestClient]:
    application = _fresh_app(monkeypatch, SESSION_HTTPS_ONLY="true", ADMIN_PASSWORD=ADMIN_PW)
    with TestClient(application, base_url="https://testserver") as c:
        yield c


# --- SEC-001 -------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize("key", ["dev-secret-change-me", "change-me-generate-a-random-64-char-hex"])
def test_cookie_forged_with_placeholder_key_gets_no_access(client, monkeypatch, key) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    client.cookies.set("session", _forge_session_cookie(key, {"admin": True}))
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


@pytest.mark.e2e
def test_legacy_admin_flag_cookie_with_real_key_gets_no_access(client, monkeypatch) -> None:
    """Even a correctly signed {'admin': True} needs a live server-side session id."""
    import os

    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    forged = _forge_session_cookie(os.environ["SECRET_KEY"], {"admin": True})
    client.cookies.set("session", forged)
    assert client.get("/admin", follow_redirects=False).status_code == 303


# --- SEC-005 -------------------------------------------------------------------


@pytest.mark.e2e
def test_session_cookie_is_secure_short_lived_lax(https_client) -> None:
    r = https_client.post("/login", data={"password": ADMIN_PW}, follow_redirects=False)
    assert r.status_code == 303
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=28800" in cookie
    assert https_client.get("/admin", follow_redirects=False).status_code == 200


# --- SEC-006 -------------------------------------------------------------------


@pytest.mark.e2e
def test_copied_cookie_is_dead_after_logout(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    assert (
        client.post("/login", data={"password": ADMIN_PW}, follow_redirects=False).status_code
        == 303
    )
    stolen = client.cookies.get("session")
    assert client.get("/admin", follow_redirects=False).status_code == 200

    client.post("/logout")
    client.cookies.set("session", stolen)
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


@pytest.mark.e2e
def test_password_change_invalidates_sessions(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    client.post("/login", data={"password": ADMIN_PW})
    assert client.get("/admin", follow_redirects=False).status_code == 200

    monkeypatch.setenv("ADMIN_PASSWORD", "a-completely-new-password")
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    # The login page must not bounce a revoked session back to /admin (no loop).
    assert client.get("/login", follow_redirects=False).status_code == 200


@pytest.mark.e2e
def test_unsetting_admin_password_invalidates_sessions(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    client.post("/login", data={"password": ADMIN_PW})
    monkeypatch.delenv("ADMIN_PASSWORD")
    assert client.get("/admin", follow_redirects=False).status_code == 303


# --- SEC-007 -------------------------------------------------------------------


@pytest.mark.e2e
def test_login_is_throttled_after_ten_failures(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    for _ in range(10):
        r = client.post("/login", data={"password": "wrong-guess"}, follow_redirects=False)
        assert r.status_code == 401
    r = client.post("/login", data={"password": "wrong-guess"}, follow_redirects=False)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    # Blocked means blocked: even the right password is not checked any more.
    r = client.post("/login", data={"password": ADMIN_PW}, follow_redirects=False)
    assert r.status_code == 429
    assert client.get("/admin", follow_redirects=False).status_code == 303


@pytest.mark.e2e
def test_throttle_is_per_client_ip(client, monkeypatch) -> None:
    from app.main import app

    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    for _ in range(10):
        client.post("/login", data={"password": "wrong-guess"})
    assert client.post("/login", data={"password": "x"}, follow_redirects=False).status_code == 429

    with TestClient(app, client=("203.0.113.7", 40000)) as other:
        r = other.post("/login", data={"password": ADMIN_PW}, follow_redirects=False)
        assert r.status_code == 303


@pytest.mark.e2e
def test_successful_login_resets_failure_count(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    for _ in range(9):
        client.post("/login", data={"password": "wrong-guess"})
    assert (
        client.post("/login", data={"password": ADMIN_PW}, follow_redirects=False).status_code
        == 303
    )
    client.post("/logout")
    for _ in range(9):
        assert (
            client.post("/login", data={"password": "nope"}, follow_redirects=False).status_code
            == 401
        )


# --- SEC-013 -------------------------------------------------------------------


@pytest.mark.e2e
def test_non_ascii_wrong_password_is_401_not_500(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    r = client.post("/login", data={"password": "ä"}, follow_redirects=False)
    assert r.status_code == 401


@pytest.mark.e2e
def test_non_ascii_admin_password_can_log_in(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "Sömmer-Passwört-2026")
    r = client.post("/login", data={"password": "Sömmer-Passwört-2026"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/admin", follow_redirects=False).status_code == 200


# --- SEC-016 -------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_api_docs_are_disabled_by_default(client, path) -> None:
    assert client.get(path).status_code == 404


@pytest.mark.e2e
def test_api_docs_can_be_enabled_explicitly(monkeypatch) -> None:
    application = _fresh_app(monkeypatch, ENABLE_API_DOCS="true")
    with TestClient(application) as c:
        assert c.get("/openapi.json").status_code == 200
        assert c.get("/docs").status_code == 200
