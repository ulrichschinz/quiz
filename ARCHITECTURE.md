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
| HTML-Templates    | 24   |
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
  Platzhalter) startet der Prozess nicht. Ein `ADMIN_PASSWORD` < 12 Zeichen bzw.
  Platzhalter wird geloggt und als nicht gesetzt behandelt (Admin-Login aus,
  öffentliche Seiten laufen weiter).
- Session-Cookie: Secure (`SESSION_HTTPS_ONLY`), HttpOnly, SameSite=Lax,
  `SESSION_MAX_AGE` (8 h). Admin-Session = Session-ID in einer In-Process-
  Allow-List (`app.core.security.admin_sessions`, absolute Ablaufzeit) +
  Passwort-Fingerprint (HMAC). Logout, Passwort-/Key-Wechsel und Neustart
  invalidieren Sessions.
- Login-Drosselung pro Client-IP (`login_throttle`, Sliding Window,
  `LOGIN_MAX_FAILURES`/`LOGIN_WINDOW_SECONDS` → 429). Schlüssel =
  `client_key()`: uvicorn-Peer, IPv4-mapped → IPv4, IPv6 → /64-Präfix.
  Hinter dem Proxy-Container nur korrekt, weil uvicorn dessen X-Forwarded-For
  vertraut: das Image setzt `FORWARDED_ALLOW_IPS` = Loopback + private Netze
  (per `.env` auf das Proxy-Subnetz einengbar). Ignoriertes X-Forwarded-For
  von einem privaten Peer wird einmal als Warnung geloggt.
- Inline-Admin-Speichern (`X-Inline: 1`) ohne gültige Session → 401 mit
  Hinweis statt Redirect; `admin-workspace.js` lädt dann nicht neu, die
  Eingaben bleiben erhalten.
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
  CRM-/Mail-Versand (Vergleich per `canonical_mailbox`: ohne `+tag`, bei
  Gmail ohne Punkte; gespeichert wird die Adresse wie eingegeben); `BodySizeLimitMiddleware` (`API_MAX_BODY_BYTES` → 413) auf `/api`.
- `app/interfaces/lead_mail.py` ist die **eine** Render-+Dispatch-Funktion für
  Submit und Admin-Retry; das Quiz wird über `submission.quiz_id` gebunden.
  Vorlagen erlauben nur `{score}` (Betreff) bzw. `{name} {score} {tier} {url}`
  (Text), geprüft beim Speichern (422) und beim Rendern (Fallback-Text, nie 500).
- Retry wiederholt nur fehlgeschlagene Legs (bei Teilablehnung nur die
  abgelehnten Empfänger), parallele Retries desselben Leads sind No-ops; der
  Zustand wird nach Erhalt des Locks neu gelesen (REV-003).
- Ergebnislinks `/r/<id>` leben nur so lange wie ihr Quiz (REV-002): ist das
  Quiz (per `submission.quiz_id`) nicht mehr veröffentlicht, gibt es eine
  neutrale 404-Seite ohne Tier-/Ergebnistexte.
- SMTP: STARTTLS bzw. SMTPS (Port 465) mit `ssl.create_default_context()`
  (Zertifikat + Hostname geprüft). Jede Nachricht hat genau einen
  Umschlagempfänger; `email_sent` nur, wenn alle Nachrichten angenommen wurden.
- CSV-Export: Zellen mit führendem `= + - @ TAB CR` erhalten ein `'`.

## Lieferkette & Deployment (Security-Audit SEC-012/018/019)

- `requirements.txt` = handgepflegte Top-Level-Pins (starlette und gepatchte
  Transitive wie anyio/mako explizit). `requirements.lock` = vollständige,
  sha256-gehashte Auflösung (`make lock`, braucht `uv`); das Image installiert
  nur daraus (`pip install --require-hashes`). Ein Unit-Test schlägt fehl, wenn
  beide auseinanderlaufen oder eine Mindestversion aus dem Audit unterschritten
  wird.
- `make audit` (pip-audit gegen `requirements.lock`) läuft in `test.yml` und vor
  jedem Deploy; der Deploy-Workflow führt vor build-and-push das volle Gate
  (`verify` + E2E) auf genau dem gebauten Commit aus.
- Alle Actions sind auf 40-stellige Commit-SHAs gepinnt (`# vX.Y.Z`-Kommentar);
  `.github/dependabot.yml` aktualisiert Actions und pip wöchentlich.
- Repo-Compose bindet die App nur an `127.0.0.1:8000`; `.dockerignore` hält
  `.env*`, `*.db`, `.venv`, `.git`, `docs/`, `tests/` aus dem Image. Der
  Container läuft als UID 10001 ohne Schreibrecht auf den Quellcode; schreibbar
  ist nur `/app/data`, dort liegt die gemountete `quiz.db` (Host-Datei `10001:0`,
  Modus 660; `DATABASE_URL=sqlite:////app/data/quiz.db`).
- SMTP-Login ohne TLS (STARTTLS aus, Port ≠ 465) wird verweigert.

## Roadmap (phased build)

1. **Skeleton + Gate** ✅ — walking skeleton, `make verify` green.
2. Data model + migrations — quizzes + submissions tables, Alembic, seed.
3. Public quiz player — `/api/quiz/{slug}` + multi-step player.
4. Scoring + results — scoring engine, submit, results page.
5. Lead pipeline — local DB + vibe CRM push + SMTP email.
6. Admin UI — session login, quiz/scoring/copy editors, leads export.
7. CI/CD + deploy — Docker, GitHub Actions, ghcr.io → adm.agentic-reach.com.
