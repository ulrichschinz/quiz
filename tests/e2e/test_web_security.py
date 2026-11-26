"""e2e regression tests for the web-hardening findings of the security audit.

SEC-008 cross-origin admin/login/logout mutations, SEC-014 security headers,
SEC-015 admin-controlled markup + CTA URLs, SEC-020 self-hosted fonts.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import db as core_db

ADMIN_PW = "correct-horse-battery-staple"
EVIL = "https://evil.example"
SELF = "http://testserver"


def _login(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    r = client.post("/login", data={"password": ADMIN_PW}, follow_redirects=False)
    assert r.status_code == 303


def _quiz_published(client: TestClient) -> bool:
    return client.get("/q/test-quiz").status_code == 200


# --- SEC-008: same-origin guard ------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": EVIL},
        {"Origin": "null"},
        {"Origin": "https://vibe.testserver"},
        {"Origin": EVIL, "Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},  # sibling subdomain: same-site, not same-origin
        {"Origin": SELF, "Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_origin_admin_post_is_403_and_has_no_effect(
    client, seeded, monkeypatch, headers
) -> None:
    _login(client, monkeypatch)
    r = client.post("/admin/quizzes/1/publish", headers=headers, follow_redirects=False)
    assert r.status_code == 403
    assert _quiz_published(client)  # toggle did NOT run


@pytest.mark.e2e
@pytest.mark.parametrize(
    "headers",
    [
        {},  # non-browser client (no Origin, no fetch metadata)
        {"Origin": SELF},
        {"Origin": SELF, "Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://TESTSERVER:80"},  # default port + case normalised
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
    ],
)
def test_same_origin_admin_post_passes(client, seeded, monkeypatch, headers) -> None:
    _login(client, monkeypatch)
    r = client.post("/admin/quizzes/1/publish", headers=headers, follow_redirects=False)
    assert r.status_code == 303
    assert not _quiz_published(client)  # toggle ran (published -> unpublished)


@pytest.mark.e2e
def test_inline_fetch_save_with_same_origin_passes(client, seeded, monkeypatch) -> None:
    """The studio's fetch() saves (X-Inline) send Origin = own origin."""
    _login(client, monkeypatch)
    r = client.post(
        "/admin/quizzes/1/landing",
        data={"hero_headline_de": "Neu", "benefits_json": "[]"},
        headers={"Origin": SELF, "Sec-Fetch-Site": "same-origin", "X-Inline": "1"},
    )
    assert r.status_code == 204


@pytest.mark.e2e
def test_cross_origin_login_and_logout_are_403(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    r = client.post(
        "/login", data={"password": ADMIN_PW}, headers={"Origin": EVIL}, follow_redirects=False
    )
    assert r.status_code == 403
    _login(client, monkeypatch)
    r = client.post("/logout", headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False)
    assert r.status_code == 403
    assert client.get("/admin", follow_redirects=False).status_code == 200  # still logged in


@pytest.mark.e2e
def test_public_submit_api_is_not_origin_guarded(client, seeded) -> None:
    payload = client.get("/api/quiz/test-quiz").json()
    answers = {str(q["id"]): q["options"][1]["id"] for q in payload["questions"]}
    r = client.post(
        "/api/quiz/test-quiz/submit",
        json={"answers": answers, "email": "l@example.com", "consent": True, "lang": "de"},
        headers={"Origin": EVIL, "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 200


@pytest.fixture
def proxied_client(engine, monkeypatch) -> Iterator[TestClient]:
    """App with APP_HOST set, reached under a different Host (proxy rewrite)."""

    def _get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    monkeypatch.setenv("APP_HOST", "quiz.example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.setattr(core_db, "create_db", lambda: None)
    from app.main import create_app

    application = create_app()
    application.dependency_overrides[core_db.get_session] = _get_session
    with TestClient(application, base_url="http://app:8000") as c:
        yield c


@pytest.mark.e2e
def test_app_host_origin_is_accepted_behind_proxy(proxied_client, seeded) -> None:
    # https Origin for the public host while the app itself sees plain http.
    r = proxied_client.post(
        "/login",
        data={"password": ADMIN_PW},
        headers={"Origin": "https://quiz.example.com"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = proxied_client.post(
        "/login",
        data={"password": ADMIN_PW},
        headers={"Origin": "https://other.example.com"},
        follow_redirects=False,
    )
    assert r.status_code == 403


# --- SEC-014: security headers -------------------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize("path", ["/q/test-quiz", "/q/test-quiz/take", "/login", "/static/quiz/quiz.css"])
def test_responses_carry_security_headers(client, seeded, path) -> None:
    r = client.get(path)
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    directives = {d.split()[0]: d for d in (x.strip() for x in csp.split(";")) if d}
    assert "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'nonce-" in directives["script-src"]
    assert directives["font-src"] == "font-src 'self'"
    assert directives["object-src"] == "object-src 'none'"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers["permissions-policy"]
    assert "strict-transport-security" not in r.headers  # plain http


@pytest.mark.e2e
def test_error_and_blocked_responses_carry_headers(client, monkeypatch) -> None:
    assert client.get("/q/does-not-exist").headers["x-frame-options"] == "DENY"
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PW)
    blocked = client.post("/login", data={"password": "x"}, headers={"Origin": EVIL})
    assert blocked.status_code == 403
    assert "content-security-policy" in blocked.headers


@pytest.mark.e2e
def test_csp_nonce_is_fresh_per_request(client) -> None:
    a = client.get("/login").headers["content-security-policy"]
    b = client.get("/login").headers["content-security-policy"]
    assert a != b


@pytest.mark.e2e
def test_hsts_only_over_https(client) -> None:
    assert "strict-transport-security" not in client.get("/login").headers
    fwd = client.get("/login", headers={"X-Forwarded-Proto": "https"})
    assert fwd.headers["strict-transport-security"] == "max-age=31536000"


@pytest.mark.e2e
def test_hsts_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HSTS_MAX_AGE", "0")
    monkeypatch.setattr(core_db, "create_db", lambda: None)
    from app.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as c:
        assert "strict-transport-security" not in c.get("/login").headers


@pytest.mark.e2e
def test_hsts_on_direct_https(monkeypatch) -> None:
    monkeypatch.setattr(core_db, "create_db", lambda: None)
    from app.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as c:
        assert c.get("/login").headers["strict-transport-security"].startswith("max-age=")


@pytest.mark.e2e
def test_pages_have_no_inline_script(client, seeded, monkeypatch) -> None:
    """With script-src lacking 'unsafe-inline', every <script> must have a src."""
    import re

    _login(client, monkeypatch)
    for path in ["/q/test-quiz", "/q/test-quiz/take", "/login", "/admin", "/admin/quizzes/1/settings"]:
        html = client.get(path).text
        for tag in re.findall(r"<script\b[^>]*>", html, flags=re.I):
            assert "src=" in tag, (path, tag)
        assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I), path


# --- SEC-015: admin markup + CTA URLs ------------------------------------------


@pytest.mark.e2e
def test_landing_escapes_admin_html_but_keeps_emphasis(client, seeded, monkeypatch) -> None:
    _login(client, monkeypatch)
    evil = "<img src=x onerror=alert(1)> bereit für das <em>agentische</em> Zeitalter"
    r = client.post(
        "/admin/quizzes/1/landing",
        data={
            "hero_headline_de": evil,
            "hero_subline_de": "<script>alert(2)</script>",
            "benefits_json": "[]",
        },
        follow_redirects=False,
    )
    assert r.status_code in (204, 303)
    html = client.get("/q/test-quiz").text
    assert "<img src=x" not in html
    assert "<script>alert(2)" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<em>agentische</em>" in html  # allowlisted emphasis still renders


def _tier_payload(cta_url: str) -> dict[str, str]:
    return {
        "quiz_id": "1",
        "name_de": "Hoch",
        "name_en": "High",
        "min_score": "50",
        "max_score": "100",
        "cta_url": cta_url,
    }


@pytest.mark.e2e
@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(document.cookie)",
        "JaVaScRiPt:alert(1)",
        " javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "//evil.example/path",
        "/\\evil.example",
    ],
)
def test_tier_cta_url_unsafe_scheme_is_422(client, seeded, monkeypatch, url) -> None:
    _login(client, monkeypatch)
    r = client.post("/admin/tiers/2", data=_tier_payload(url), headers={"X-Inline": "1"})
    assert r.status_code == 422
    # Not stored: the results CTA still points at the default booking URL.
    tiers = client.get("/admin/quizzes/1/scoring").text
    assert "javascript:" not in tiers.lower() and "data:text" not in tiers


@pytest.mark.e2e
def test_tier_cta_url_unsafe_without_js_is_not_saved(client, seeded, monkeypatch) -> None:
    _login(client, monkeypatch)
    r = client.post("/admin/tiers/2", data=_tier_payload("javascript:alert(1)"), follow_redirects=False)
    assert r.status_code == 303
    assert "javascript:" not in client.get("/admin/quizzes/1/scoring").text


@pytest.mark.e2e
@pytest.mark.parametrize("url", ["https://cal.example.com/book", "http://example.com", "/kontakt", ""])
def test_tier_cta_url_safe_values_are_saved(client, seeded, monkeypatch, url) -> None:
    _login(client, monkeypatch)
    r = client.post("/admin/tiers/2", data=_tier_payload(url), headers={"X-Inline": "1"})
    assert r.status_code == 200
    if url:
        assert f'value="{url}"' in r.text


@pytest.mark.e2e
def test_legacy_unsafe_cta_url_falls_back_to_default(client, seeded, engine) -> None:
    """A javascript: value stored before validation existed never reaches a href."""
    from sqlmodel import select

    from app.domains.quizzes.models import ResultTier

    with Session(engine) as s:
        for t in s.exec(select(ResultTier)).all():
            t.cta_url = "javascript:alert(1)"
            s.add(t)
        s.commit()
    payload = client.get("/api/quiz/test-quiz").json()
    answers = {str(q["id"]): q["options"][1]["id"] for q in payload["questions"]}
    sub = client.post(
        "/api/quiz/test-quiz/submit",
        json={"answers": answers, "email": "l@example.com", "consent": True, "lang": "de"},
    ).json()
    html = client.get(sub["redirect"]).text
    assert "javascript:" not in html
    assert 'href="https://agentic-reach.com/?lang=de"' in html


# --- SEC-020: self-hosted fonts ------------------------------------------------


@pytest.mark.e2e
def test_pages_reference_no_google_fonts(client, seeded) -> None:
    for path in ["/q/test-quiz", "/login", "/static/brand/brand-kit.css", "/static/brand/typography.css"]:
        body = client.get(path).text
        assert "fonts.googleapis.com" not in body and "fonts.gstatic.com" not in body, path


@pytest.mark.e2e
@pytest.mark.parametrize(
    "font",
    [
        "space-grotesk-latin-wght-normal.woff2",
        "jetbrains-mono-latin-wght-normal.woff2",
        "fraunces-latin-opsz-normal.woff2",
        "fraunces-latin-opsz-italic.woff2",
    ],
)
def test_self_hosted_font_files_are_served(client, font) -> None:
    css = client.get("/static/brand/fonts/fonts.css")
    assert css.status_code == 200 and font in css.text
    r = client.get(f"/static/brand/fonts/{font}")
    assert r.status_code == 200
    assert r.content[:4] == b"wOF2"
