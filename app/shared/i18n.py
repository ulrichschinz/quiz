"""app.shared.i18n — DE/EN language helpers for server-rendered copy.

All user-facing model fields come in `_de`/`_en` pairs. `pick` resolves the
active language with a German default (DACH audience), falling back to whatever
is present so a half-translated quiz never renders an empty string.
"""

from __future__ import annotations

LANGUAGES = ("de", "en")
DEFAULT_LANG = "de"


def normalize_lang(lang: str | None) -> str:
    """Clamp an arbitrary input to a supported language code."""
    return lang if lang in LANGUAGES else DEFAULT_LANG


def pick(de: str | None, en: str | None, lang: str) -> str:
    """Return the value for `lang`, falling back to the other language."""
    lang = normalize_lang(lang)
    primary, secondary = (en, de) if lang == "en" else (de, en)
    return (primary or secondary or "").strip()
