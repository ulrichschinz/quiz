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
| HTTP-Endpoints    | 43   |
| HTML-Templates    | 20   |
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

## Code-Index (software-repo-prompt.md Säulen 8 + 9)

A repo-owned, agent-agnostic index of `app/` (+ `templates/`) lives in the
top-level `codeindex/` package (stdlib-only; tooling, like `scripts/`, so it is
outside the Kennzahlen and import-linter scope). It answers the four navigation
questions for any agent arriving cold:

| Frage | Befehl |
| --- | --- |
| wo ist X | `python -m codeindex where <name>` |
| wer benutzt/importiert X | `python -m codeindex uses <name>` / `who-imports <modul>` |
| was bricht bei Änderung von X | `python -m codeindex impact <modul\|datei>` |
| wo machen wir das schon | `make index-q Q="…"` (`search`) |

- **Reachable two ways:** the CLI above (any agent with a shell) and a stdio MCP
  server `python -m codeindex.mcp_server` (MCP-native agents; needs the optional
  `requirements-mcp.txt`). Register via `.mcp.json` → server `codeindex`.
- **Freshness (Säule 9):** the build stores a file fingerprint; every answer
  prints a `# index: FRESH|STALE → rebuilt` banner and self-heals on query.
  `make index-hooks` installs git hooks that rebuild on pull/checkout.
- **Artifact** `.code-index/` is gitignored — only the tooling is checked in.
- Edges static analysis cannot know (domain auto-discovery in `app/main.py`, DI,
  reflection, Jinja→route) are left empty, never guessed. See
  `docs/decisions/0001-code-index.md`.

## Roadmap (phased build)

1. **Skeleton + Gate** ✅ — walking skeleton, `make verify` green.
2. Data model + migrations — quizzes + submissions tables, Alembic, seed.
3. Public quiz player — `/api/quiz/{slug}` + multi-step player.
4. Scoring + results — scoring engine, submit, results page.
5. Lead pipeline — local DB + vibe CRM push + SMTP email.
6. Admin UI — session login, quiz/scoring/copy editors, leads export.
7. CI/CD + deploy — Docker, GitHub Actions, ghcr.io → adm.agentic-reach.com.
