"""e2e: admin auth gate + the login → build → publish → leads HTTP flow."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
def test_admin_requires_login(client) -> None:
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


@pytest.mark.e2e
def test_wrong_password_is_rejected(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    r = client.post("/login", data={"password": "nope"}, follow_redirects=False)
    assert r.status_code == 401


@pytest.mark.e2e
def test_login_build_publish_and_export(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")

    login = client.post("/login", data={"password": "secret"}, follow_redirects=False)
    assert login.status_code == 303

    created = client.post(
        "/admin/quizzes",
        data={"slug": "built", "title_de": "Gebaut", "title_en": "Built"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    quiz_id = int(created.headers["location"].rsplit("/", 1)[1])

    # The editor page renders.
    edit = client.get(f"/admin/quizzes/{quiz_id}")
    assert edit.status_code == 200
    assert "Gebaut" in edit.text

    # Add a dimension, then publish → the public landing becomes reachable.
    client.post(
        f"/admin/quizzes/{quiz_id}/dimensions",
        data={"key": "k", "name_de": "K", "name_en": "K", "weight": "1.0"},
    )
    client.post(f"/admin/quizzes/{quiz_id}/publish")

    public = client.get("/q/built")
    assert public.status_code == 200

    # CSV export works.
    csv = client.get(f"/admin/quizzes/{quiz_id}/leads.csv")
    assert csv.status_code == 200
    assert "text/csv" in csv.headers["content-type"]
    assert "email" in csv.text  # header row


def _login_and_build(client, monkeypatch) -> tuple[int, int]:
    """Log in, create a quiz with one dimension + question. Returns (quiz_id, question_id)."""
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client.post("/login", data={"password": "secret"})
    created = client.post(
        "/admin/quizzes",
        data={"slug": "inline", "title_de": "Inline", "title_en": "Inline"},
        follow_redirects=False,
    )
    quiz_id = int(created.headers["location"].rsplit("/", 1)[1])
    client.post(
        f"/admin/quizzes/{quiz_id}/dimensions",
        data={"key": "d", "name_de": "D", "name_en": "D", "weight": "1.0"},
    )
    dim_id = 1  # first dimension of a fresh DB
    client.post(
        f"/admin/quizzes/{quiz_id}/questions",
        data={"dimension_id": dim_id, "text_de": "F", "text_en": "Q"},
    )
    return quiz_id, 1


@pytest.mark.e2e
def test_inline_add_option_returns_fragment_not_redirect(client, monkeypatch) -> None:
    quiz_id, question_id = _login_and_build(client, monkeypatch)

    # No header -> the no-JS path still 303-redirects (progressive enhancement).
    plain = client.post(
        f"/admin/questions/{question_id}/options",
        data={"quiz_id": quiz_id, "label_de": "Ja", "label_en": "Yes", "weight": "1.0"},
        follow_redirects=False,
    )
    assert plain.status_code == 303

    # With X-Inline -> a standalone option-row fragment, no full page.
    frag = client.post(
        f"/admin/questions/{question_id}/options",
        data={"quiz_id": quiz_id, "label_de": "Nein", "label_en": "No", "weight": "0.0"},
        headers={"X-Inline": "1"},
    )
    assert frag.status_code == 200
    assert 'data-card data-replace' in frag.text
    assert "Nein" in frag.text
    assert "<html" not in frag.text  # a fragment, not the whole editor page


@pytest.mark.e2e
def test_inline_accepts_german_decimal_comma(client, monkeypatch) -> None:
    quiz_id, question_id = _login_and_build(client, monkeypatch)
    ok = client.post(
        f"/admin/questions/{question_id}/options",
        data={"quiz_id": quiz_id, "label_de": "Halb", "label_en": "Half", "weight": "0,5"},
        headers={"X-Inline": "1"},
    )
    assert ok.status_code == 200
    assert 'value="0.5"' in ok.text  # "0,5" was parsed to 0.5

    bad = client.post(
        f"/admin/questions/{question_id}/options",
        data={"quiz_id": quiz_id, "label_de": "X", "label_en": "X", "weight": "abc"},
        headers={"X-Inline": "1"},
    )
    assert bad.status_code == 422
    assert "Gewicht" in bad.text


@pytest.mark.e2e
def test_inline_delete_returns_204(client, monkeypatch) -> None:
    quiz_id, question_id = _login_and_build(client, monkeypatch)
    client.post(
        f"/admin/questions/{question_id}/options",
        data={"quiz_id": quiz_id, "label_de": "Ja", "label_en": "Yes", "weight": "1.0"},
        headers={"X-Inline": "1"},
    )
    gone = client.post(
        f"/admin/options/1/delete",
        data={"quiz_id": quiz_id},
        headers={"X-Inline": "1"},
    )
    assert gone.status_code == 204


@pytest.mark.e2e
def test_inline_tier_min_max_validation(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    bad = client.post(
        f"/admin/quizzes/{quiz_id}/tiers",
        data={"name_de": "Bad", "name_en": "Bad", "min_score": "80", "max_score": "20"},
        headers={"X-Inline": "1"},
    )
    assert bad.status_code == 422
    assert "Min" in bad.text


@pytest.mark.e2e
def test_editor_renders_section_rail_and_collapsible_questions(client, monkeypatch) -> None:
    quiz_id, question_id = _login_and_build(client, monkeypatch)
    page = client.get(f"/admin/quizzes/{quiz_id}")
    assert page.status_code == 200
    # Section rail (Phase 2 overview) is present...
    assert 'data-ws-nav' in page.text
    assert 'data-ws-link="questions"' in page.text
    # ...and questions render as collapsible <details> cards with a summary.
    assert "data-question-card" in page.text
    assert "ws-summary" in page.text


@pytest.mark.e2e
def test_inline_add_question_returns_details_fragment(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    frag = client.post(
        f"/admin/quizzes/{quiz_id}/questions",
        data={"dimension_id": 1, "text_de": "Zweite", "text_en": "Second"},
        headers={"X-Inline": "1"},
    )
    assert frag.status_code == 200
    assert "<details" in frag.text and "data-question-card" in frag.text
    assert "Zweite" in frag.text
    assert "<html" not in frag.text


@pytest.mark.e2e
def test_add_question_without_dimension_is_friendly_422(client, monkeypatch) -> None:
    # Fresh quiz with NO dimensions: the dimension <select> posts nothing.
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client.post("/login", data={"password": "secret"})
    created = client.post(
        "/admin/quizzes",
        data={"slug": "nodim", "title_de": "ND", "title_en": "ND"},
        follow_redirects=False,
    )
    quiz_id = int(created.headers["location"].rsplit("/", 1)[1])
    r = client.post(
        f"/admin/quizzes/{quiz_id}/questions",
        data={"text_de": "F", "text_en": "Q"},  # no dimension_id
        headers={"X-Inline": "1"},
    )
    assert r.status_code == 422
    assert "Dimension" in r.text
    assert "detail" not in r.text  # not the raw FastAPI validation JSON


@pytest.mark.e2e
def test_tier_non_integer_score_is_friendly_422(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    r = client.post(
        f"/admin/quizzes/{quiz_id}/tiers",
        data={"name_de": "T", "name_en": "T", "min_score": "12.5", "max_score": "100"},
        headers={"X-Inline": "1"},
    )
    assert r.status_code == 422
    assert "ganze Zahlen" in r.text


@pytest.mark.e2e
def test_logout_clears_session(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client.post("/login", data={"password": "secret"})
    client.post("/logout")
    assert client.get("/admin", follow_redirects=False).status_code == 303
