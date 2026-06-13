"""app.shared.links — canonical Agentic Reach destinations (language-aware).

Cross-cutting helper (no domain logic): the "book a call" CTA points at the
marketing landing page, in the visitor's language. Kept here so both the results
page and the result email resolve the same default.
"""

from __future__ import annotations

from app.shared.i18n import normalize_lang

_CALL_BOOKING = "https://agentic-reach.com/?lang={lang}"
_CALL_LABEL = {"de": "Gespräch vereinbaren →", "en": "Book a call →"}


def call_booking_url(lang: str) -> str:
    """The 'book a call' target — the marketing landing page."""
    return _CALL_BOOKING.format(lang=normalize_lang(lang))


def call_label(lang: str) -> str:
    """Default label for the book-a-call CTA."""
    return _CALL_LABEL[normalize_lang(lang)]
