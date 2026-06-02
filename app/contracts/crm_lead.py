"""Anti-corruption DTO for the vibe CRM lead-ingestion endpoint.

Mirrors vibe's `LeadCreate` (`POST /api/leads`, `X-API-Key`): the quiz app
never imports vibe's models — this single DTO is the seam. The scorecard's
score + per-dimension breakdown ride along in `agent_metadata` so the CRM /
weekly lead pipeline can use them.
"""

from __future__ import annotations

from pydantic import BaseModel


class CrmLead(BaseModel):
    name: str | None = None
    company: str | None = None
    email: str | None = None
    source: str = "website"
    notes: str | None = None
    tags: list[str] | None = None
    agent_metadata: dict | None = None
