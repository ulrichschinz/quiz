"""e2e: submitting the quiz computes + persists a score and renders results."""

from __future__ import annotations

import pytest


def _all_yes_answers(client) -> dict[str, int]:
    """Pick the second option (the weight-1.0 'Yes') for every question."""
    payload = client.get("/api/quiz/test-quiz").json()
    return {str(q["id"]): q["options"][1]["id"] for q in payload["questions"]}


@pytest.mark.e2e
def test_submit_then_results_shows_score(client, seeded) -> None:
    resp = client.post(
        "/api/quiz/test-quiz/submit",
        json={
            "answers": _all_yes_answers(client),
            "email": "lead@example.com",
            "name": "Dana",
            "company": "ACME",
            "consent": True,
            "lang": "de",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["redirect"].startswith("/r/")

    result = client.get(body["redirect"])
    assert result.status_code == 200
    assert "100/100" in result.text or "100<" in result.text
    assert "Hoch" in result.text  # the high tier name


@pytest.mark.e2e
def test_submit_unknown_quiz_is_404(client, seeded) -> None:
    resp = client.post(
        "/api/quiz/nope/submit",
        json={"answers": {}, "email": "x@example.com", "lang": "de"},
    )
    assert resp.status_code == 404


@pytest.mark.e2e
def test_results_unknown_id_is_404(client, seeded) -> None:
    assert client.get("/r/doesnotexist").status_code == 404
