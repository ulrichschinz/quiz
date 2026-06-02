"""interfaces.web.auth — single-password admin login/logout (session cookie)."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.security import SESSION_ADMIN_KEY, verify_admin_password

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get(SESSION_ADMIN_KEY):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"error": None})


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    if verify_admin_password(password, get_settings().admin_password):
        request.session[SESSION_ADMIN_KEY] = True
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        request, "admin/login.html", {"error": "Falsches Passwort."}, status_code=401
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
