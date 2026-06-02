"""Application package — Soll layout (bounded domains).

Layout (see AGENTS.md for the contract):
- app.core       reusable kernel: config, db, security, errors, logging
- app.contracts  anti-corruption DTOs for outbound integrations (vibe CRM)
- app.shared     cross-cutting helpers (i18n) with no domain logic
- app.domains    bounded contexts: quizzes (config) + submissions (leads)
- app.interfaces delivery layer: web (Jinja SSR) + api (JSON)
"""
