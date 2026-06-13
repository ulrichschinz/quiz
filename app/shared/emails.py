"""app.shared.emails — render the branded result emails (customer + team).

Cross-cutting presentation helper (no domain logic), like i18n. Email clients
strip <style>, external CSS and web fonts, so these templates use table layout,
inline styles, web-safe font stacks and the hard hex values from
`app.shared.scoring_display` (not the brand-kit CSS variables). Kept out of the
submissions domain so the lead pipeline stays a dumb transmitter of finished
bytes; an interface (the API submit handler) calls this and hands the result on.
"""

from __future__ import annotations

import html as _html
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.shared.scoring_display import level_color

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"]),
)
_env.globals["level_color"] = level_color

# Light wordmark reads on the plum email header.
LOGO_PATH = "/static/brand/logos/png/lockup-horizontal-mono-light-400.png"


def _intro_html(text: str, *, link_url: str | None = None) -> str:
    """Escape the admin's plaintext message, linkify the result URL, keep breaks."""
    safe = _html.escape(text)
    if link_url:
        safe_url = _html.escape(link_url)
        safe = safe.replace(
            safe_url,
            f'<a href="{safe_url}" style="color:#FF7A6B;">{safe_url}</a>',
        )
    return safe.replace("\n", "<br>")


def render_customer_email(
    *,
    lang: str,
    intro_text: str,
    overall_score: int,
    tier_name: str,
    tier_headline: str,
    tier_body: str,
    dimensions: list[tuple[str, int]],
    show_breakdown: bool,
    cta_label: str | None,
    cta_url: str | None,
    result_url: str,
    logo_url: str,
) -> str:
    """Render the full branded HTML result email for the lead."""
    dims = [
        {"name": name, "score": score, "color": level_color(score)} for name, score in dimensions
    ]
    template = _env.get_template("email/result_customer.html")
    return template.render(
        lang=lang,
        intro_html=_intro_html(intro_text, link_url=result_url),
        overall_score=overall_score,
        overall_color=level_color(overall_score),
        tier_name=tier_name,
        tier_headline=tier_headline,
        tier_body=tier_body,
        dimensions=dims,
        show_breakdown=show_breakdown,
        cta_label=cta_label,
        cta_url=cta_url,
        result_url=result_url,
        logo_url=logo_url,
    )


def render_team_email(
    *,
    overall_score: int,
    tier_name: str | None,
    breakdown: list[
        Any
    ],  # quizzes.schemas.DimensionBreakdown (duck-typed to avoid a domain import)
    lead_name: str | None,
    lead_email: str | None,
    lead_company: str | None,
    consent: bool,
    result_url: str,
    logo_url: str,
) -> tuple[str, str]:
    """Render the internal lead-notification email (HTML + plaintext fallback).

    Always German (internal DACH team); the answer labels keep the language the
    lead actually saw. Returns (html, text).
    """
    html = _env.get_template("email/result_team.html").render(
        overall_score=overall_score,
        overall_color=level_color(overall_score),
        tier_name=tier_name or "",
        breakdown=breakdown,
        lead_name=lead_name or "—",
        lead_email=lead_email or "—",
        lead_company=lead_company or "—",
        consent=consent,
        result_url=result_url,
        logo_url=logo_url,
    )
    text = _team_text(
        overall_score=overall_score,
        tier_name=tier_name or "—",
        breakdown=breakdown,
        lead_name=lead_name or "—",
        lead_email=lead_email or "—",
        lead_company=lead_company or "—",
        consent=consent,
        result_url=result_url,
    )
    return html, text


def _team_text(
    *,
    overall_score: int,
    tier_name: str,
    breakdown: list[Any],
    lead_name: str,
    lead_email: str,
    lead_company: str,
    consent: bool,
    result_url: str,
) -> str:
    lines = [
        f"Neuer Lead: {lead_name} <{lead_email}> ({lead_company})",
        f"Score: {overall_score}/100 ({tier_name})",
        f"Einwilligung: {'ja' if consent else 'nein'}",
        "",
    ]
    for dim in breakdown:
        lines.append(f"{dim.name} — {dim.score}/100")
        for qa in dim.questions:
            mark = f"{qa.value}/100" if qa.answered else "nicht beantwortet"
            lines.append(f"  • {qa.question}: {qa.answer} ({mark})")
        lines.append("")
    lines.append(f"Vollständiges Ergebnis: {result_url}")
    return "\n".join(lines)
