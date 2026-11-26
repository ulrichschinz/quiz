"""Unit regression tests: SEC-014/015/020 (sanitizer, URL allowlist, static scans)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.http_security import build_csp
from app.shared.links import is_safe_link_url
from app.shared.safe_html import inline_html

REPO = Path(__file__).resolve().parents[2]


# --- SEC-015: inline_html allowlist -------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ist Ihre Organisation bereit für das <em>agentische</em> KI-Zeitalter?",
         "Ist Ihre Organisation bereit für das <em>agentische</em> KI-Zeitalter?"),
        ("<strong>fett</strong> und<br>neu<br/>zeile<BR />", "<strong>fett</strong> und<br>neu<br>zeile<br>"),
        ("<img src=x onerror=alert(1)>", "&lt;img src=x onerror=alert(1)&gt;"),
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ('<em onclick="x()">a</em>', "&lt;em onclick=&#34;x()&#34;&gt;a</em>"),
        ("<a href='javascript:x'>a</a>", "&lt;a href=&#39;javascript:x&#39;&gt;a&lt;/a&gt;"),
        ("Tom & Jerry", "Tom &amp; Jerry"),
        (None, ""),
    ],
)
def test_inline_html_allowlist(raw, expected) -> None:
    assert str(inline_html(raw)) == expected


def test_seed_headline_still_renders_emphasis() -> None:
    seed = (REPO / "scripts" / "seed_flagship.py").read_text(encoding="utf-8")
    headlines = re.findall(r'hero_headline_(?:de|en)="([^"]+)"', seed)
    assert headlines
    for h in headlines:
        assert str(inline_html(h)) == h  # only allowlisted markup in the flagship copy


# --- SEC-015: link URL allowlist -----------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["https://agentic-reach.com/?lang=de", "http://example.com/x#y", "HTTPS://EXAMPLE.COM", "/kontakt", "/"],
)
def test_safe_link_urls(url) -> None:
    assert is_safe_link_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "java\nscript:alert(1)",
        " https://example.com",
        "data:text/html,x",
        "vbscript:x",
        "mailto:a@b.c",
        "//evil.example",
        "/\\evil.example",
        "https:evil",
        "https:///nohost",
        "kontakt",
    ],
)
def test_unsafe_link_urls(url) -> None:
    assert not is_safe_link_url(url)


# --- SEC-014: CSP + no inline script/handlers in templates and static ----------


def test_csp_has_no_unsafe_script_sources() -> None:
    csp = build_csp("abc")
    script_src = next(d for d in csp.split("; ") if d.startswith("script-src"))
    assert script_src == "script-src 'self' 'nonce-abc'"
    assert "frame-ancestors 'none'" in csp
    assert "font-src 'self'" in csp


def _files(*globs: str) -> list[Path]:
    out: list[Path] = []
    for g in globs:
        out += [p for p in REPO.glob(g) if p.is_file()]
    return out


def test_templates_have_no_inline_scripts_or_handlers() -> None:
    for path in _files("templates/**/*.html"):
        if "email" in path.parts:
            continue  # e-mails are not served under our CSP and carry no script
        html = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<script\b[^>]*>", html, flags=re.I):
            assert "src=" in tag, f"inline <script> in {path}"
        assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I), f"inline handler in {path}"
        assert "javascript:" not in html.lower(), path


def test_language_switch_never_uses_innerhtml() -> None:
    js = (REPO / "static" / "quiz" / "lang.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    assert "innerHTML" not in code
    assert "renderInline" in code


# --- SEC-020: no third-party font requests -------------------------------------


def test_no_google_fonts_references() -> None:
    for path in _files("templates/**/*.html", "static/**/*.css", "static/**/*.js"):
        text = path.read_text(encoding="utf-8")
        assert "fonts.googleapis.com" not in text, path
        assert "fonts.gstatic.com" not in text, path


def test_font_faces_point_at_vendored_files_with_licence() -> None:
    fonts = REPO / "static" / "brand" / "fonts"
    css = (fonts / "fonts.css").read_text(encoding="utf-8")
    refs = set(re.findall(r"url\('\./([^']+)'\)", css))
    assert refs
    for ref in refs:
        assert (fonts / ref).is_file(), ref
    for family in ("Space Grotesk", "JetBrains Mono", "Fraunces"):
        assert f"font-family: '{family}'" in css
    for lic in ("OFL-Fraunces.txt", "OFL-SpaceGrotesk.txt", "OFL-JetBrainsMono.txt"):
        assert "SIL OPEN FONT LICENSE" in (fonts / lic).read_text(encoding="utf-8").upper()


# --- SEC-006 review follow-up: an expired session never discards admin input --


def test_inline_save_does_not_reload_on_login_redirect() -> None:
    js = (REPO / "static" / "admin" / "admin-workspace.js").read_text()
    login_guard = js.index("/\\/login(?:[?#]|$)/.test(res.url)")
    reload_call = js.index("window.location.reload()")
    assert login_guard < reload_call  # the /login case is handled before any reload
    assert "Sitzung abgelaufen" in js
