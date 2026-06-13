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
        data={"quiz_id": quiz_id, "label_de": "Ja", "label_en": "Yes"},
        follow_redirects=False,
    )
    assert plain.status_code == 303

    # With X-Inline -> the re-rendered options section, no full page.
    frag = client.post(
        f"/admin/questions/{question_id}/options",
        data={"quiz_id": quiz_id, "label_de": "Nein", "label_en": "No"},
        headers={"X-Inline": "1"},
    )
    assert frag.status_code == 200
    assert "data-options" in frag.text  # the re-rendered options section wrapper
    assert "Nein" in frag.text
    assert "<html" not in frag.text  # a fragment, not the whole editor page


@pytest.mark.e2e
def test_inline_add_option_shows_derived_percent(client, monkeypatch) -> None:
    # Options have no weight field any more — the value is derived from the
    # ranking (add order = best → worst) and rendered read-only as a %.
    quiz_id, question_id = _login_and_build(client, monkeypatch)
    base = {"quiz_id": quiz_id}
    client.post(
        f"/admin/questions/{question_id}/options",
        data={**base, "label_de": "Best", "label_en": "Best"},
        headers={"X-Inline": "1"},
    )
    frag = client.post(
        f"/admin/questions/{question_id}/options",
        data={**base, "label_de": "Worst", "label_en": "Worst"},
        headers={"X-Inline": "1"},
    )
    assert frag.status_code == 200
    assert "100%" in frag.text and "0%" in frag.text  # extremes derived from rank


@pytest.mark.e2e
def test_inline_delete_recomputes_options(client, monkeypatch) -> None:
    quiz_id, question_id = _login_and_build(client, monkeypatch)
    base = {"quiz_id": quiz_id}
    client.post(
        f"/admin/questions/{question_id}/options",
        data={**base, "label_de": "Ja", "label_en": "Yes"},
        headers={"X-Inline": "1"},
    )
    client.post(
        f"/admin/questions/{question_id}/options",
        data={**base, "label_de": "Nein", "label_en": "No"},
        headers={"X-Inline": "1"},
    )
    # Delete the first (best) option -> the section re-renders and the survivor
    # becomes the only answer at 100 %.
    resp = client.post("/admin/options/1/delete", data=base, headers={"X-Inline": "1"})
    assert resp.status_code == 200
    assert "data-options" in resp.text
    assert "100%" in resp.text


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
def test_studio_overview_renders_sidebar_and_dashboard(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    page = client.get(f"/admin/quizzes/{quiz_id}")
    assert page.status_code == 200
    assert "studio-nav" in page.text  # fixed sidebar
    assert f'href="/admin/quizzes/{quiz_id}/questions"' in page.text
    assert "Startklar?" in page.text  # the completeness checklist
    assert "tile-grid" in page.text  # dashboard tiles


@pytest.mark.e2e
def test_studio_section_pages_render(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    for path, marker in [
        ("/questions", "qlist"),
        ("/scoring", "Bewertungs-Stufen"),
        ("/landing", "Augenbraue"),
        ("/results", "E-Mail-Text"),
        ("/settings", "Quiz löschen"),
        ("/leads", "lead-table"),
    ]:
        r = client.get(f"/admin/quizzes/{quiz_id}{path}")
        assert r.status_code == 200, path
        assert marker in r.text, path


@pytest.mark.e2e
def test_add_question_redirects_into_its_editor(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    r = client.post(
        f"/admin/quizzes/{quiz_id}/questions",
        data={"dimension_id": 1, "text_de": "Zweite", "text_en": "Second"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert f"/admin/quizzes/{quiz_id}/questions/" in r.headers["location"]


@pytest.mark.e2e
def test_add_dimension_derives_key_from_name(client, monkeypatch) -> None:
    # The scoring add-form no longer posts a "key"; the route derives it.
    quiz_id, _ = _login_and_build(client, monkeypatch)
    r = client.post(
        f"/admin/quizzes/{quiz_id}/dimensions",
        data={"name_de": "Strategie & Vision", "name_en": "Strategy"},
        headers={"X-Inline": "1"},
    )
    assert r.status_code == 200
    assert 'value="strategie_vision"' in r.text  # key derived from the German name
    assert "data-dimensions" in r.text  # rendered back as the dimensions section


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
def test_publish_returns_to_originating_area(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    r = client.post(
        f"/admin/quizzes/{quiz_id}/publish",
        headers={"Referer": f"http://x/admin/quizzes/{quiz_id}/scoring"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith(f"/admin/quizzes/{quiz_id}/scoring")


@pytest.mark.e2e
def test_meta_empty_slug_is_friendly_422(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    r = client.post(
        f"/admin/quizzes/{quiz_id}/meta",
        data={"slug": "", "title_de": "X", "estimated_minutes": "3"},
        headers={"X-Inline": "1"},
    )
    assert r.status_code == 422
    assert "Slug" in r.text and "detail" not in r.text


@pytest.mark.e2e
def test_question_focus_foreign_id_redirects_to_list(client, monkeypatch) -> None:
    quiz_id, _ = _login_and_build(client, monkeypatch)
    r = client.get(f"/admin/quizzes/{quiz_id}/questions/99999", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith(f"/admin/quizzes/{quiz_id}/questions")


@pytest.mark.e2e
def test_logout_clears_session(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client.post("/login", data={"password": "secret"})
    client.post("/logout")
    assert client.get("/admin", follow_redirects=False).status_code == 303
