"""Anti-corruption DTOs for outbound integrations.

A domain never imports another system's models. Outbound payloads (e.g. the
vibe CRM lead) are defined here as plain DTOs so the integration shape is a
single, reviewable seam — added in Phase 5 (`crm_lead.py`).
"""
