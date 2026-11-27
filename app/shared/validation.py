"""app.shared.validation — strict input checks for untrusted, mail-bound text.

Cross-cutting helpers (no domain logic, stdlib only), used by the submissions
DTOs and the quiz admin:

* `normalize_email_address` (SEC-002/017) — accepts exactly ONE plain
  ``local@domain`` address. Anything an SMTP library could read as a list or a
  display-name form (commas, semicolons, whitespace, angle brackets, quotes,
  several ``@``, control characters) is rejected, so the customer mail always has
  exactly one envelope recipient. Deliberately stricter than RFC 5322: no quoted
  local parts, no comments, no IP-literal domains, ASCII local part only.
* `clean_single_line` (SEC-002/003) — strip + length bound + no control
  characters / line or paragraph separators / bidi overrides for short free-text
  fields (name, company) that end up in e-mails and the CRM.
* `template_errors` / `format_template` (SEC-011) — ``str.format`` templates the
  admin edits: only whitelisted bare placeholders (no ``{x.y}`` / ``{x[0]}`` /
  positional ``{}`` / conversions / format specs); rendering never raises.
"""

from __future__ import annotations

import string
import unicodedata
from collections.abc import Iterable, Mapping

EMAIL_MAX_LENGTH = 254  # RFC 5321 path limit
_LOCAL_MAX_LENGTH = 64
_LABEL_MAX_LENGTH = 63
# RFC 5322 "atext" (dot-atom) — notably WITHOUT , ; < > ( ) [ ] : \ " and space.
_LOCAL_CHARS = frozenset(string.ascii_letters + string.digits + "!#$%&'*+/=?^_`{|}~-.")
_LABEL_CHARS = frozenset(string.ascii_letters + string.digits + "-")
_BIDI_CONTROLS = frozenset("‪‫‬‭‮⁦⁧⁨⁩")


def normalize_email_address(raw: str) -> str:
    """Return the single address (domain lower-cased / IDNA-encoded) or raise ValueError."""
    value = raw.strip()
    if not value:
        raise ValueError("email address is required")
    if len(value) > EMAIL_MAX_LENGTH:
        raise ValueError("email address is too long")
    if value.count("@") != 1:
        raise ValueError("exactly one email address is required")
    local, domain = value.split("@")
    if not local or len(local) > _LOCAL_MAX_LENGTH:
        raise ValueError("invalid email address")
    if any(ch not in _LOCAL_CHARS for ch in local):
        raise ValueError("invalid email address")
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("invalid email address")

    try:
        ascii_domain = domain.encode("idna").decode("ascii") if not domain.isascii() else domain
    except UnicodeError as exc:
        raise ValueError("invalid email domain") from exc
    ascii_domain = ascii_domain.lower()
    labels = ascii_domain.split(".")
    if len(labels) < 2:
        raise ValueError("invalid email domain")
    for label in labels:
        if not label or len(label) > _LABEL_MAX_LENGTH:
            raise ValueError("invalid email domain")
        if any(ch not in _LABEL_CHARS for ch in label):
            raise ValueError("invalid email domain")
        if label.startswith("-") or label.endswith("-"):
            raise ValueError("invalid email domain")
    tld = labels[-1]
    if len(tld) < 2 or not (tld.isalpha() or tld.startswith("xn--")):
        raise ValueError("invalid email domain")

    address = f"{local}@{ascii_domain}"
    if len(address) > EMAIL_MAX_LENGTH:
        raise ValueError("email address is too long")
    return address


def _forbidden_char(ch: str) -> bool:
    return unicodedata.category(ch) in {"Cc", "Zl", "Zp"} or ch in _BIDI_CONTROLS


def clean_single_line(raw: str | None, *, max_length: int) -> str | None:
    """Strip; empty -> None; raise ValueError if too long or not a single clean line."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise ValueError(f"must be at most {max_length} characters")
    if any(_forbidden_char(ch) for ch in value):
        raise ValueError("must not contain control characters or line breaks")
    return value


def template_errors(template: str, allowed: Iterable[str]) -> list[str]:
    """Problems with a ``str.format`` template; empty list == safe to render."""
    allowed_set = set(allowed)
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        return [f"Ungültige Klammern: {exc}"]
    problems: list[str] = []
    for _literal, field, spec, conversion in parsed:
        if field is None:
            continue  # plain text (or an escaped {{ / }})
        if field not in allowed_set:
            problems.append(f"Unbekannter Platzhalter {{{field}}}")
        elif conversion or spec:
            problems.append(f"Platzhalter {{{field}}} ohne Zusätze verwenden")
    return problems


def format_template(template: str, allowed: Iterable[str], values: Mapping[str, object]) -> str:
    """Render a template validated by `template_errors`; raise ValueError if invalid.

    Only the whitelisted names are offered to ``format_map`` (and the template is
    re-checked first), so attribute/index traversal can never run.
    """
    allowed_set = set(allowed)
    problems = template_errors(template, allowed_set)
    if problems:
        raise ValueError("; ".join(problems))
    return template.format_map({k: values.get(k, "") for k in allowed_set})
