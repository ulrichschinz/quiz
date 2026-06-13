"""Quizzes domain — good default copy for a freshly created quiz.

Every generic text field on `QuizResultConfig` / `QuizLandingConfig` ships with
sensible, on-brand German + English defaults so a new quiz reads well out of the
box and the admin only has to *tweak* copy, never invent it from scratch. These
constants are the single source of truth: the model `Field` defaults reference
them (so `create_quiz` auto-fills every new quiz), and the seed reuses them.

Placeholders available in the e-mail templates: ``{name}`` ``{score}`` ``{tier}``
``{url}`` (subject supports ``{score}``). Keep braces only around those.
"""

from __future__ import annotations

import json

# --- Result page + e-mail --------------------------------------------------
INTRO_DE = "Dein persönliches Ergebnis"
INTRO_EN = "Your personal result"

EMAIL_SUBJECT_DE = "Dein Ergebnis: {score}/100 — Agentic Reach"
EMAIL_SUBJECT_EN = "Your result: {score}/100 — Agentic Reach"

EMAIL_BODY_DE = (
    "Hallo {name},\n\n"
    "vielen Dank, dass du dir die Zeit für unsere Umfrage genommen hast. "
    "Dein Ergebnis steht fest: {score}/100 — {tier}.\n\n"
    "Deine vollständige Auswertung mit konkreten nächsten Schritten findest du hier:\n"
    "{url}\n\n"
    "Wenn du die Ergebnisse gemeinsam besprechen möchtest, melde dich jederzeit gern.\n\n"
    "Herzliche Grüße\n"
    "Dein Team von Agentic Reach"
)
EMAIL_BODY_EN = (
    "Hi {name},\n\n"
    "thank you for taking the time to complete our survey. "
    "Here is your result: {score}/100 — {tier}.\n\n"
    "Your full evaluation, including concrete next steps, is available here:\n"
    "{url}\n\n"
    "If you'd like to go through the results together, feel free to reach out any time.\n\n"
    "Best regards,\n"
    "The Agentic Reach team"
)

NOTIFY_EMAILS = "leads@agentic-reach.com"

# --- Landing page ----------------------------------------------------------
HERO_EYEBROW_DE = "// Agentic Reach"
HERO_EYEBROW_EN = "// Agentic Reach"
HERO_HEADLINE_DE = "Wie zukunftsfähig ist deine Organisation?"
HERO_HEADLINE_EN = "How future-ready is your organization?"
HERO_SUBLINE_DE = (
    "In wenigen Minuten herausfinden — kostenlos, unverbindlich und mit "
    "konkreten nächsten Schritten."
)
HERO_SUBLINE_EN = (
    "Find out in just a few minutes — free, non-binding, and with concrete next steps."
)
CTA_LABEL_DE = "Quiz starten →"
CTA_LABEL_EN = "Start the quiz →"
BENEFITS_JSON = json.dumps(
    [
        {"de": "In wenigen Minuten erledigt", "en": "Done in just a few minutes"},
        {"de": "Sofort-Score von 0–100", "en": "Instant score from 0–100"},
        {"de": "Konkrete nächste Schritte", "en": "Concrete next steps"},
    ],
    ensure_ascii=False,
)
