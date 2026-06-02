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


@pytest.mark.e2e
def test_logout_clears_session(client, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    client.post("/login", data={"password": "secret"})
    client.post("/logout")
    assert client.get("/admin", follow_redirects=False).status_code == 303
