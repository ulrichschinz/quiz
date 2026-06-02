# Agentic Reach — Quiz / Scorecard

Self-hosted quiz/scorecard lead-generation app (a ScoreApp.com replacement) in
the Agentic Reach design. A visitor takes a ~3-minute quiz, gets a 0–100
readiness score with a tiered evaluation, and becomes a warm lead that flows to
the vibe CRM, the team inbox and a local DB. Questions, landing copy and
evaluations are all configurable through a password-protected admin UI.

## Stack
FastAPI · SQLModel · SQLite · Alembic · Jinja2 (SSR) · vanilla JS on the
vendored Agentic Reach brand kit. Mirrors the conventions of the sibling
`vibe` service. See **CLAUDE.md** for the agent contract and **ARCHITECTURE.md**
for the CI-verified structure.

## Develop
```bash
python3.12 -m venv .venv
make dev-install            # runtime + dev deps into .venv
make seed                   # load the flagship "Agentic AI Readiness" quiz
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/  (public)   ·   /admin  (login with ADMIN_PASSWORD)
```

Copy `.env.example` → `.env` and set at least `SECRET_KEY` and `ADMIN_PASSWORD`.
Set `CRM_INGEST_URL` + `CRM_API_KEY` and the `SMTP_*` vars to enable the CRM and
email legs of the lead pipeline (both skip cleanly when unset).

## The gate
```bash
make verify   # lint + format-check + typecheck + import-contracts + tests + doc-gate
```
A green gate is the definition of mergeable. `make new-quiz <name>` scaffolds a
new bounded domain that is gate-green by construction.

## Deploy
Push to `main` → GitHub Actions builds the image → `ghcr.io` → SSH
forced-command `docker compose pull && up -d` on `adm.agentic-reach.com`
(`quiz.agentic-reach.com`). Requires the repo secrets `DEPLOY_HOST`,
`DEPLOY_USER`, `DEPLOY_SSH_KEY`.
