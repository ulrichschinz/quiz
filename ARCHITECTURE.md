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
| HTTP-Endpoints    | 44   |
| HTML-Templates    | 23   |
| SQLModel-Tabellen | 8    |

- **Domains** — sub-packages under `app/domains/` (`quizzes`, `submissions`).
- **Route-Module** — router modules under `app/interfaces/{web,api}/` plus any
  `app/domains/*/router.py` (currently `web/public.py`, `api/router.py`).
- **HTTP-Endpoints** — `@router.<method>` decorators across those modules
  (`GET /`, `GET /api/health`).
- **HTML-Templates** — files under `templates/` (`base.html`,
  `public/landing.html`, `email/result_customer.html`).
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

## Admin-Auth (Security-Audit SEC-001/005/006/007/013/016)

- `Settings` ist fail-closed: ohne starken `SECRET_KEY` (>= 32 Zeichen, kein
  Platzhalter) oder mit `ADMIN_PASSWORD` < 12 Zeichen startet der Prozess nicht.
- Session-Cookie: Secure (`SESSION_HTTPS_ONLY`), HttpOnly, SameSite=Lax,
  `SESSION_MAX_AGE` (8 h). Admin-Session = Session-ID in einer In-Process-
  Allow-List (`app.core.security.admin_sessions`, absolute Ablaufzeit) +
  Passwort-Fingerprint (HMAC). Logout, Passwort-/Key-Wechsel und Neustart
  invalidieren Sessions.
- Login-Drosselung pro Client-IP (`login_throttle`, Sliding Window,
  `LOGIN_MAX_FAILURES`/`LOGIN_WINDOW_SECONDS` → 429). IP = uvicorn-Peer;
  hinter einem Proxy nur korrekt mit `FORWARDED_ALLOW_IPS` = Proxy-Adresse.
- Annahme: **ein** uvicorn-Prozess. Mehrere Worker/Replicas brauchen einen
  gemeinsamen Store für Session-Registry und Throttle.
- `/docs`, `/redoc`, `/openapi.json` nur mit `ENABLE_API_DOCS=true`.

## Web-Härtung (Security-Audit SEC-008/014/015/020)

- `app.core.http_security` (reines ASGI, in `app/main.py` verdrahtet):
  - `SameOriginGuardMiddleware`: POST/PUT/PATCH/DELETE auf `/admin…`, `/login`,
    `/logout` → 403 bei `Sec-Fetch-Site: cross-site|same-site` oder fremdem
    `Origin` (erlaubt: eigener `Host` bzw. `APP_HOST`). Ohne beide Header
    (Nicht-Browser) durchgelassen. `/api/*` (anonymer Submit) ist ausgenommen.
  - `SecurityHeadersMiddleware`: auf jeder Antwort CSP (`script-src 'self'
    'nonce-…'`, kein Inline-Skript; `style-src 'unsafe-inline'` bewusst für
    `style=`-Attribute der Templates/Ergebnis-Charts; `font-src 'self'`,
    `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`,
    `Referrer-Policy`, `Permissions-Policy`; HSTS (`HSTS_MAX_AGE`) nur bei https
    bzw. `X-Forwarded-Proto: https`. Nonce: `request.state.csp_nonce`.
- Keine Inline-Skripte/-Handler: Sprachumschalter in `static/quiz/lang.js`,
  Lösch-Bestätigungen per `data-confirm` (`static/admin/admin-workspace.js`).
- Admin-Texte: nie `|safe`; Filter `inline_html` (`app.shared.safe_html`)
  escaped alles außer `<em>`, `<strong>`, `<br>`; `lang.js` baut DOM-Knoten mit
  derselben Allowlist statt `innerHTML`. Tier-`cta_url` nur `http(s)://` oder
  relativer Pfad (`app.shared.links.is_safe_link_url`, sonst 422).
- Schriften selbst gehostet unter `static/brand/fonts/` (woff2, OFL) — keine
  Anfrage an Google Fonts.

## Lead-Strecke (Security-Audit SEC-002/003/004/009/010/011/017, REV-001/003)

- Submit-DTO (`SubmitRequest`): `email` = genau **eine** gültige Adresse
  (`app.shared.validation.normalize_email_address`, keine Listen/Display-Names/
  Steuerzeichen; Pflichtfeld = Lead-Gate), `name`/`company` einzeilig, <= 200
  Zeichen, `answers` <= 200 Einträge.
- `quizzes.service.answer_errors`: nur Fragen/Optionen dieses Quiz, alle
  Pflichtfragen beantwortet, sonst 422.
- Missbrauchsgrenzen: `submit_throttle` pro Client-IP
  (`SUBMIT_MAX_PER_MINUTE`/`SUBMIT_MAX_PER_HOUR` → 429), gleiche E-Mail + Quiz
  innerhalb `SUBMIT_DEDUP_WINDOW_SECONDS` → gespeichert, aber kein erneuter
  CRM-/Mail-Versand; `BodySizeLimitMiddleware` (`API_MAX_BODY_BYTES` → 413) auf `/api`.
- `app/interfaces/lead_mail.py` ist die **eine** Render-+Dispatch-Funktion für
  Submit und Admin-Retry; das Quiz wird über `submission.quiz_id` gebunden.
  Vorlagen erlauben nur `{score}` (Betreff) bzw. `{name} {score} {tier} {url}`
  (Text), geprüft beim Speichern (422) und beim Rendern (Fallback-Text, nie 500).
- Retry wiederholt nur fehlgeschlagene Legs (bei Teilablehnung nur die
  abgelehnten Empfänger), parallele Retries desselben Leads sind No-ops.
- SMTP: STARTTLS bzw. SMTPS (Port 465) mit `ssl.create_default_context()`
  (Zertifikat + Hostname geprüft). Jede Nachricht hat genau einen
  Umschlagempfänger; `email_sent` nur, wenn alle Nachrichten angenommen wurden.
- CSV-Export: Zellen mit führendem `= + - @ TAB CR` erhalten ein `'`.

## Roadmap (phased build)

1. **Skeleton + Gate** ✅ — walking skeleton, `make verify` green.
2. Data model + migrations — quizzes + submissions tables, Alembic, seed.
3. Public quiz player — `/api/quiz/{slug}` + multi-step player.
4. Scoring + results — scoring engine, submit, results page.
5. Lead pipeline — local DB + vibe CRM push + SMTP email.
6. Admin UI — session login, quiz/scoring/copy editors, leads export.
7. CI/CD + deploy — Docker, GitHub Actions, ghcr.io → adm.agentic-reach.com.
