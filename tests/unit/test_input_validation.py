"""Unit: strict single-address / single-line / template validators (SEC-002/011/017)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domains.quizzes.admin import email_template_errors
from app.domains.submissions.schemas import SubmitRequest
from app.shared.validation import (
    clean_single_line,
    format_template,
    normalize_email_address,
    template_errors,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lead@example.com", "lead@example.com"),
        ("  Dana.Lee+quiz@Example.COM ", "Dana.Lee+quiz@example.com"),
        ("x@müller.de", "x@xn--mller-kva.de"),
    ],
)
def test_single_valid_address_is_accepted(raw: str, expected: str) -> None:
    assert normalize_email_address(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "a@x.de, b@y.de",
        "a@x.de; b@y.de",
        "a@x.de b@y.de",
        "a@x.de\r\nBcc: b@y.de",
        "Dana <a@x.de>",
        '"a b"@x.de',
        "a@@x.de",
        "a@b@x.de",
        "a@localhost",
        "a@x..de",
        "a@-x.de",
        ".a@x.de",
        "a..b@x.de",
        "a@x.d",
        "a@x.12",
        "a" * 65 + "@x.de",
        "a@" + "b" * 250 + ".de",
    ],
)
def test_lists_and_malformed_addresses_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_email_address(raw)


def test_single_line_cleaning() -> None:
    assert clean_single_line("  ACME GmbH ", max_length=200) == "ACME GmbH"
    assert clean_single_line("   ", max_length=200) is None
    assert clean_single_line(None, max_length=200) is None
    for bad in ("a\nb", "a\rb", "a\x00b", "a b", "evil‮exe.pdf", "x" * 201):
        with pytest.raises(ValueError):
            clean_single_line(bad, max_length=200)


def test_submit_request_bounds() -> None:
    ok = SubmitRequest(answers={1: 2}, email="lead@example.com", name=" Dana ")
    assert ok.name == "Dana" and ok.company is None
    for bad in (
        {"answers": {1: 2}, "email": "a@x.de, b@y.de"},
        {"answers": {1: 2}, "email": ""},
        {"answers": {1: 2}, "email": "lead@example.com", "name": "x" * 201},
        {"answers": {1: 2}, "email": "lead@example.com", "company": "a\nb"},
        {"answers": {i: 1 for i in range(1, 202)}, "email": "lead@example.com"},
        {"answers": {1: 2**40}, "email": "lead@example.com"},
        {"answers": {-1: 2}, "email": "lead@example.com"},
    ):
        with pytest.raises(ValidationError):
            SubmitRequest(**bad)


def test_template_whitelist() -> None:
    allowed = {"name", "score", "tier", "url"}
    assert template_errors("Hallo {name}, {score}/100 {{literal}}", allowed) == []
    for bad in ("{vorname}", "{name.__class__}", "{name[0]}", "{}", "{0}", "10 }", "{score!r}", "{score:>9}"):
        assert template_errors(bad, allowed), bad
    assert format_template("Hi {name} {{x}}", allowed, {"name": "{score}"}) == "Hi {score} {x}"
    with pytest.raises(ValueError):
        format_template("{name.__init__}", allowed, {"name": "x"})


def test_email_template_errors_names_the_field() -> None:
    problems = email_template_errors(
        email_subject_de="Score {score}",
        email_subject_en="Score {name}",  # name is not offered in the subject
        email_body_de="Hallo {vorname}",
        email_body_en="Hi {name}",
    )
    assert any(p.startswith("Betreff (EN)") for p in problems)
    assert any(p.startswith("Text (DE)") for p in problems)
    assert not any(p.startswith("Text (EN)") for p in problems)
