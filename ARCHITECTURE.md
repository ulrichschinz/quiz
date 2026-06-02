# ARCHITECTURE.md — Ist-Zustand

The CI-verified contract of the current structure. `scripts/check_contract.py`
(the `doc-gate` step of `make verify`) asserts the tables below against the
code on every run; drift fails the build. Update this file in the same change
that changes the structure.

## Kennzahlen

| Metrik            | Wert |
| ----------------- | ---- |
| Domains           | 2    |
| Route-Module      | 4    |
| HTTP-Endpoints    | 34   |
| HTML-Templates    | 8    |
| SQLModel-Tabellen | 8    |

- **Domains** — sub-packages under `app/domains/` (`quizzes`, `submissions`).
- **Route-Module** — router modules under `app/interfaces/{web,api}/` plus any
  `app/domains/*/router.py` (currently `web/public.py`, `api/router.py`).
- **HTTP-Endpoints** — `@router.<method>` decorators across those modules
  (`GET /`, `GET /api/health`).
- **HTML-Templates** — files under `templates/` (`base.html`,
  `public/landing.html`).
- **SQLModel-Tabellen** — `class … (table=True)` definitions under `app/`.

## Struktur-Verträge (CI-erzwungen)

import-linter contracts in `pyproject.toml`, enforced by `make contracts`.

| Contract                      |
| ----------------------------- |
| `app.core is domain-agnostic` |
| `domains are independent`     |
| `interfaces reach domains via services, not models` |

## Roadmap (phased build)

1. **Skeleton + Gate** ✅ — walking skeleton, `make verify` green.
2. Data model + migrations — quizzes + submissions tables, Alembic, seed.
3. Public quiz player — `/api/quiz/{slug}` + multi-step player.
4. Scoring + results — scoring engine, submit, results page.
5. Lead pipeline — local DB + vibe CRM push + SMTP email.
6. Admin UI — session login, quiz/scoring/copy editors, leads export.
7. CI/CD + deploy — Docker, GitHub Actions, ghcr.io → adm.agentic-reach.com.
