"""Unit tests for the language-aware canonical links."""

from __future__ import annotations

from app.shared.links import call_booking_url, call_label


def test_booking_url_is_language_specific() -> None:
    assert call_booking_url("de") == "https://agentic-reach.com/?lang=de"
    assert call_booking_url("en") == "https://agentic-reach.com/?lang=en"
    # An unsupported code clamps to the German default.
    assert call_booking_url("fr") == "https://agentic-reach.com/?lang=de"


def test_call_label_is_localized() -> None:
    assert "Gespräch" in call_label("de")
    assert "call" in call_label("en").lower()
