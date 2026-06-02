"""Unit tests for the DE/EN language helper."""

from __future__ import annotations

from app.shared.i18n import normalize_lang, pick


def test_pick_prefers_active_language() -> None:
    assert pick("Hallo", "Hi", "de") == "Hallo"
    assert pick("Hallo", "Hi", "en") == "Hi"


def test_pick_falls_back_when_translation_missing() -> None:
    assert pick("Hallo", None, "en") == "Hallo"
    assert pick(None, "Hi", "de") == "Hi"
    assert pick(None, None, "de") == ""


def test_normalize_lang_clamps_to_supported() -> None:
    assert normalize_lang("en") == "en"
    assert normalize_lang("fr") == "de"
    assert normalize_lang(None) == "de"
