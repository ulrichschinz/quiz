"""app.main — FastAPI application assembly.

`load_dotenv()` runs before the engine-bearing modules construct anything from
settings at import time (db.py reads DATABASE_URL at module load), so the
imports below are deliberately ordered after it — hence the file-scoped E402
ignore in pyproject.toml.

The delivery layer is wired through `app.interfaces.{web,api}`: `web.register`
includes the Jinja routers (+ domain auto-discovery), `api.register` mounts the
JSON router. `NeedsLoginException` (raised by `require_admin`) maps to a login
redirect (a 401 with a message for inline admin saves, `X-Inline: 1`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import PlainTextResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import create_db  # noqa: E402
from app.core.errors import NeedsLoginException  # noqa: E402
from app.core.http_security import (  # noqa: E402
    BodySizeLimitMiddleware,
    SameOriginGuardMiddleware,
    SecurityHeadersMiddleware,
)
from app.interfaces import api as api_iface  # noqa: E402
from app.interfaces import web as web_iface  # noqa: E402

STATIC_DIR = Path(__file__).parent.parent / "static"
INLINE_SESSION_EXPIRED = "Sitzung abgelaufen – bitte in neuem Tab anmelden, dann erneut speichern."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_db()
    yield


def create_app() -> FastAPI:
    """Build the ASGI app from the current Settings.

    Constructing Settings here is the fail-closed startup check (SEC-001/007):
    a missing/weak SECRET_KEY or too-short ADMIN_PASSWORD raises before the app
    exists. API docs are off unless ENABLE_API_DOCS (SEC-016). The session
    cookie is Secure (SESSION_HTTPS_ONLY), HttpOnly, SameSite=Lax and lives
    SESSION_MAX_AGE seconds (SEC-005). Lax rather than Strict: Strict would drop
    the cookie on every cross-site navigation (e.g. a link from a lead e-mail
    into /admin) without adding CSRF protection for top-level POSTs beyond Lax.
    CSRF beyond Lax: SameOriginGuardMiddleware rejects unsafe requests to
    /admin, /login, /logout whose Origin / Sec-Fetch-Site is not same-origin
    (SEC-008). SecurityHeadersMiddleware adds CSP, X-Frame-Options, nosniff,
    Referrer-/Permissions-Policy and HSTS on https (SEC-014).
    BodySizeLimitMiddleware caps /api request bodies at API_MAX_BODY_BYTES (SEC-003).
    """
    settings = get_settings()
    docs = settings.enable_api_docs
    application = FastAPI(
        title="Agentic Reach Quiz",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.session_https_only,
    )
    # Added after the session middleware => runs *before* it (outermost last):
    # cross-origin admin/login/logout mutations are refused without touching
    # the session (SEC-008), and every response — 403s and static files
    # included — carries the security headers (SEC-014).
    application.add_middleware(SameOriginGuardMiddleware, app_host=settings.app_host)
    # SEC-003: cap the public JSON API's request body (413) before parsing.
    application.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.api_max_body_bytes)
    application.add_middleware(SecurityHeadersMiddleware, hsts_max_age=settings.hsts_max_age)

    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @application.exception_handler(NeedsLoginException)
    async def needs_login_handler(request: Request, exc: NeedsLoginException) -> Response:
        # Inline admin saves (fetch + `X-Inline: 1`) get a 401 with a message
        # instead of a redirect, so the editor keeps the unsaved input and tells
        # the admin to log in again (sessions end on restart / after 8 h).
        if request.headers.get("x-inline") == "1":
            return PlainTextResponse(INLINE_SESSION_EXPIRED, status_code=401)
        return RedirectResponse(url="/login", status_code=303)

    web_iface.register(application)
    api_iface.register(application)
    return application


app = create_app()
