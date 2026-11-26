"""app.shared.links — canonical Agentic Reach destinations (language-aware).

Cross-cutting helper (no domain logic): the "book a call" CTA points at the
marketing landing page, in the visitor's language. Kept here so both the results
page and the result email resolve the same default.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.shared.i18n import normalize_lang

_CALL_BOOKING = "https://agentic-reach.com/?lang={lang}"
_CALL_LABEL = {"de": "Gespräch vereinbaren →", "en": "Book a call →"}


def call_booking_url(lang: str) -> str:
    """The 'book a call' target — the marketing landing page."""
    return _CALL_BOOKING.format(lang=normalize_lang(lang))


def call_label(lang: str) -> str:
    """Default label for the book-a-call CTA."""
    return _CALL_LABEL[normalize_lang(lang)]


def is_safe_link_url(url: str) -> bool:
    """True for an admin-configurable link target that cannot run script (SEC-015).

    Allowed: absolute ``http://`` / ``https://`` URLs with a host, and site-
    relative paths (``/…``, not the protocol-relative ``//host``). Everything
    else — ``javascript:``, ``data:``, ``vbscript:``, ``mailto:``, bare words,
    backslash or control-character tricks (browsers strip tabs/newlines inside
    schemes, ``java\\tscript:``) — is rejected. The empty string is NOT a URL;
    callers treat "" as "unset" before asking.
    """
    if not url or url != url.strip():
        return False
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in url) or "\\" in url:
        return False
    if url.startswith("/"):
        return not url.startswith("//")
    parts = urlsplit(url)
    return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)
