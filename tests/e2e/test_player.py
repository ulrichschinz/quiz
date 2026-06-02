"""e2e: the public landing, the player JSON payload, and the player shell."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
def test_root_redirects_to_published_quiz(client, seeded) -> None:
    resp = client.get("/")  # follows the 303 to /q/test-quiz
    assert resp.status_code == 200
    assert "Bereit?" in resp.text
    assert "Ready?" in resp.text  # both languages embedded for the toggle


@pytest.mark.e2e
def test_landing_is_data_driven(client, seeded) -> None:
    resp = client.get("/q/test-quiz")
    assert resp.status_code == 200
    assert "/q/test-quiz/take" in resp.text  # CTA points at the player
    assert "Start DE" in resp.text
    assert "Benefit" in resp.text


@pytest.mark.e2e
def test_quiz_payload_omits_weights(client, seeded) -> None:
    resp = client.get("/api/quiz/test-quiz")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["questions"]) == 2
    assert "weight" not in resp.text
    first_option = data["questions"][0]["options"][0]
    assert set(first_option.keys()) == {"id", "label_de", "label_en"}


@pytest.mark.e2e
def test_player_shell_loads_player_js(client, seeded) -> None:
    resp = client.get("/q/test-quiz/take")
    assert resp.status_code == 200
    assert 'id="quiz-app"' in resp.text
    assert "/static/quiz/player.js" in resp.text
    assert 'data-slug="test-quiz"' in resp.text


@pytest.mark.e2e
def test_unknown_quiz_is_404(client, seeded) -> None:
    assert client.get("/q/nope").status_code == 404
    assert client.get("/api/quiz/nope").status_code == 404
