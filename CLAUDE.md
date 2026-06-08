# CLAUDE.md — agent contract

Self-hosted quiz / scorecard lead-generation app (a ScoreApp.com replacement)
for Agentic Reach. A visitor takes a ~3-minute quiz, gets a 0–100 readiness
score with a tiered evaluation, and becomes a warm lead that flows to the vibe
CRM, the team inbox and a local DB. Everything (questions, landing copy,
evaluations) is configurable through a password-protected admin UI.

## Sources of truth
- **ARCHITECTURE.md** — the Ist-state Kennzahlen, CI-verified by
  `scripts/check_contract.py` (the `doc-gate`).
- **CLAUDE.md** (this file) — the rules below.

## Organizing principle: bounded domains
Code is organized by *what changes together*, not by technical layer.

```
app/
  core/        reusable kernel: config, db, security, errors, logging
  contracts/   anti-corruption DTOs for outbound integrations (vibe CRM)
  shared/      cross-cutting helpers (i18n) — no domain logic
  domains/
    quizzes/      quiz configuration + scoring (Quiz, Dimension, Question, …)
    submissions/  lead capture + results (Submission, lead pipeline)
  interfaces/
    web/        Jinja2 SSR routers (public site, auth, admin)
    api/        public JSON API (quiz player, submit)
templates/     Jinja2 templates (brand-kit styled)
static/        brand/ (vendored brand kit) + quiz/ (app css + player js)
migrations/    Alembic (single tree)
scripts/       scaffold + contract self-check + seed
tests/         unit / integration / e2e
```

## Allowed-dependency rules (executable — import-linter, `make contracts`)
- `app.core` imports **nothing** of ours (domain-agnostic kernel).
- Domains are **independent**: `submissions` references a quiz only by string
  FK + copied scores, never `import app.domains.quizzes`.
- `interfaces` reach domains through `service` modules, not `*.models`.
- Outbound integrations go through `app.contracts.*` DTOs — a domain never
  imports another system's models.

## Where does a change of kind X go?
- New quiz field / scoring rule → `app/domains/quizzes/`.
- Lead capture / results / pipeline → `app/domains/submissions/`.
- New page or form → `app/interfaces/web/`; new JSON endpoint → `app/interfaces/api/`.
- New env var → `app/core/config.py` (`Settings`), documented in `.env.example`.
- A whole new bounded context → `make new-quiz <name>` (never hand-create files).

## Navigate with the code index first
Before grepping, ask the repo-owned index (stdlib, self-healing):
`python -m codeindex where|uses|impact <X>`, `make index-q Q="…"`. It answers
"where is X / who uses X / what breaks if I change X / where do we already do
this". Agent-agnostic (CLI for any shell; optional MCP server
`python -m codeindex.mcp_server`). See ARCHITECTURE.md → Code-Index.

## Edit order within a domain
`models.py → schemas.py → service.py → (router/interface) → tests`.

## Acceptance gate (definition of mergeable)
```
make verify    # lint + format-check + typecheck + contracts + test-fast + doc-gate
```
Keep `main` shippable and the gate green at every step. Dev commands:
`make dev-install`, `uvicorn app.main:app --reload`, `make seed`, `make fmt`.

## Deployment
git push to `main` → GitHub Actions builds the image → ghcr.io → SSH
forced-command `docker compose pull && up -d` on `adm.agentic-reach.com`
(same path as the sibling `vibe` service).
