"""Walking-skeleton e2e: the app boots, serves the branded landing + health."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
def test_landing_renders_with_brand(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # The brand kit is wired in (single import) and the hero copy is present.
    assert "/static/brand/brand-kit.css" in body
    assert "Agentic" in body


@pytest.mark.e2e
def test_health_ok(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
