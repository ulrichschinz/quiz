"""Unit tests for the branded customer-email renderer."""

from __future__ import annotations

from app.shared import emails


def _render(**overrides):
    kwargs = dict(
        lang="de",
        intro_text="Hallo Dana,\nschau dir https://x.y/r/abc an.",
        overall_score=82,
        tier_name="Hoch",
        tier_headline="Stark aufgestellt",
        tier_body="Weiter so.",
        dimensions=[("Strategie", 30), ("Daten", 90)],
        show_breakdown=True,
        cta_label="Gespräch vereinbaren",
        cta_url="https://x.y/call",
        result_url="https://x.y/r/abc",
        logo_url="https://x.y/static/logo.png",
    )
    kwargs.update(overrides)
    return emails.render_customer_email(**kwargs)


def test_renders_score_and_traffic_light_colours() -> None:
    html = _render()
    assert "82" in html
    assert "#4F9D69" in html  # overall 82 → high/green
    assert "#D1493B" in html  # dimension 30 → low/red
    assert "Stark aufgestellt" in html and "Gespräch vereinbaren" in html
    assert 'href="https://x.y/call"' in html


def test_intro_is_escaped_and_url_linkified() -> None:
    html = _render(intro_text="A <script>x</script> link https://x.y/r/abc here")
    assert "<script>" not in html  # user copy is escaped
    assert "&lt;script&gt;" in html
    assert '<a href="https://x.y/r/abc"' in html  # result URL linkified


def test_breakdown_hidden_when_disabled() -> None:
    html = _render(show_breakdown=False)
    assert "Deine Dimensionen" not in html


def test_team_email_shows_answers_lead_and_colours() -> None:
    from app.domains.quizzes.schemas import AnsweredQuestion, DimensionBreakdown

    breakdown = [
        DimensionBreakdown(
            name="Strategie",
            score=30,
            questions=[
                AnsweredQuestion(question="KI-Strategie?", answer="Nein", value=0, answered=True),
                AnsweredQuestion(question="Budget?", answer="—", value=0, answered=False),
            ],
        )
    ]
    html, text = emails.render_team_email(
        overall_score=30,
        tier_name="Niedrig",
        breakdown=breakdown,
        lead_name="Dana",
        lead_email="dana@acme.test",
        lead_company="ACME",
        consent=True,
        result_url="https://x.y/r/abc",
        logo_url="https://x.y/l.png",
    )
    # The team sees the questions, the chosen answers and the lead contact.
    assert "KI-Strategie?" in html and "Nein" in html
    assert "ACME" in html and "dana@acme.test" in html
    assert "#D1493B" in html  # overall 30 → red
    assert "k. A." in html  # unanswered marker
    # Plaintext fallback carries the same facts.
    assert "Neuer Lead: Dana" in text and "30/100" in text
    assert "nicht beantwortet" in text and "https://x.y/r/abc" in text
