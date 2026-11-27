"""interfaces.web.auth — single-password admin login/logout (session cookie).

Failed logins are throttled per client IP (`app.core.security.login_throttle`,
SEC-007): after LOGIN_MAX_FAILURES failures within LOGIN_WINDOW_SECONDS the IP
gets 429 + Retry-After. The check runs *before* the password comparison, so a
blocked client cannot keep guessing. A successful login resets that IP's count.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.security import (
    client_key,
    end_admin_session,
    is_admin,
    login_throttle,
    start_admin_session,
    verify_admin_password,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"error": None})


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    settings = get_settings()
    key = client_key(request)
    wait = login_throttle.retry_after(
        key, settings.login_max_failures, settings.login_window_seconds
    )
    if wait:
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"error": "Zu viele Fehlversuche. Bitte später erneut versuchen."},
            status_code=429,
            headers={"Retry-After": str(wait)},
        )
    if verify_admin_password(password, settings.admin_password):
        login_throttle.reset(key)
        start_admin_session(request)
        return RedirectResponse("/admin", status_code=303)
    login_throttle.record_failure(key, settings.login_window_seconds)
    return templates.TemplateResponse(
        request, "admin/login.html", {"error": "Falsches Passwort."}, status_code=401
    )


@router.post("/logout")
def logout(request: Request):
    end_admin_session(request)
    return RedirectResponse("/login", status_code=303)
