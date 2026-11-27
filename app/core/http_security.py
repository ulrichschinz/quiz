"""app.core.http_security — HTTP-level hardening middleware (pure ASGI).

Two small, domain-agnostic middlewares wired in `app/main.py`:

* `SameOriginGuardMiddleware` (SEC-008) — CSRF defence-in-depth on top of the
  SameSite=Lax session cookie. Unsafe methods (POST/PUT/PATCH/DELETE) to the
  protected paths (`/admin…`, `/login`, `/logout`) are rejected with 403 when
  the browser marks them as not same-origin:
    - ``Sec-Fetch-Site: cross-site`` or ``same-site`` (a sibling subdomain is
      *same-site* but not same-origin — exactly the residual risk of Lax), or
    - an ``Origin`` header that is not this app's own origin (request ``Host``
      header, or ``APP_HOST``), including ``Origin: null``.
  Requests with neither header (curl, the TestClient, very old browsers) pass:
  every current browser sends ``Origin`` on a POST. The public JSON API
  (`/api/...`) is not covered — it is anonymous by design.

* `BodySizeLimitMiddleware` (SEC-003) — requests under the given prefixes
  (the public ``/api``) whose body exceeds ``max_bytes`` get 413: immediately
  when ``Content-Length`` says so, otherwise as soon as the streamed body
  crosses the limit (chunked uploads), before the app parses it.

* `SecurityHeadersMiddleware` (SEC-014) — sets on *every* response:
  Content-Security-Policy, X-Frame-Options: DENY, X-Content-Type-Options:
  nosniff, Referrer-Policy, Permissions-Policy, and Strict-Transport-Security
  when the request arrived over https (directly or per ``X-Forwarded-Proto``
  from the TLS-terminating proxy; ``HSTS_MAX_AGE=0`` disables it).
  A fresh CSP nonce per request is exposed as ``request.state.csp_nonce``
  (``scope["state"]["csp_nonce"]``): an inline ``<script>`` must carry
  ``nonce="{{ request.state.csp_nonce }}"`` — there are none today, all
  scripts are files under /static. ``style-src`` keeps ``'unsafe-inline'``
  on purpose: templates and the result charts use ``style="…"`` attributes
  (inline SVG colours/geometry) — style injection cannot execute script.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_PROTECTED_PREFIXES: tuple[str, ...] = ("/admin", "/login", "/logout")
_DEFAULT_PORTS = {"http": "80", "https": "443"}
# Paths whose built-in UI loads third-party assets (FastAPI's Swagger/ReDoc
# from a CDN). Only reachable with ENABLE_API_DOCS (local dev) — no CSP there.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key == name:
            return str(value.decode("latin-1"))
    return None


def _normalize_netloc(netloc: str, scheme: str) -> str:
    """Lower-case host[:port] with the scheme's default port stripped."""
    netloc = netloc.strip().lower()
    default = _DEFAULT_PORTS.get(scheme)
    if default and netloc.endswith(":" + default) and not netloc.endswith("]"):
        netloc = netloc[: -(len(default) + 1)]
    return netloc


def _path_protected(path: str, prefixes: Iterable[str]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


class SameOriginGuardMiddleware:
    """403 for cross-origin unsafe requests to the session-authenticated UI (SEC-008)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        app_host: str = "",
        protected_prefixes: Iterable[str] = DEFAULT_PROTECTED_PREFIXES,
    ) -> None:
        self.app = app
        self.protected_prefixes = tuple(protected_prefixes)
        host = app_host.strip()
        if "://" in host:
            host = urlsplit(host).netloc
        self.app_host = host.lower()

    def _origin_allowed(self, scope: Scope, origin: str) -> bool:
        parts = urlsplit(origin)
        if parts.scheme not in _DEFAULT_PORTS or not parts.netloc:
            return False  # "null", file:, chrome-extension:, garbage …
        origin_netloc = _normalize_netloc(parts.netloc, parts.scheme)
        req_scheme = scope.get("scheme", "http")
        # Behind a TLS-terminating proxy the app sees http while the browser's
        # Origin is https — accept that, but never an http Origin for an https app.
        if parts.scheme == "http" and req_scheme == "https":
            return False
        allowed = set()
        host = _header(scope, b"host")
        if host:
            allowed.add(_normalize_netloc(host, req_scheme))
            allowed.add(_normalize_netloc(host, parts.scheme))
        if self.app_host:
            allowed.add(_normalize_netloc(self.app_host, parts.scheme))
        return origin_netloc in allowed

    def _blocked(self, scope: Scope) -> bool:
        if scope.get("method", "GET").upper() not in UNSAFE_METHODS:
            return False
        if not _path_protected(scope.get("path", ""), self.protected_prefixes):
            return False
        fetch_site = (_header(scope, b"sec-fetch-site") or "").strip().lower()
        if fetch_site in {"cross-site", "same-site"}:
            return True
        origin = _header(scope, b"origin")
        if origin is not None:
            return not self._origin_allowed(scope, origin.strip())
        # No Origin: allow only non-browser clients / same-origin fetch metadata.
        return fetch_site not in {"", "same-origin", "none"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._blocked(scope):
            body = b"Cross-origin request blocked."
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """413 for request bodies above `max_bytes` under `prefixes` (SEC-003)."""

    def __init__(
        self, app: ASGIApp, *, max_bytes: int, prefixes: Iterable[str] = ("/api",)
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.prefixes = tuple(prefixes)

    async def _reject(self, send: Send) -> None:
        body = b'{"detail":"request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _path_protected(scope.get("path", ""), self.prefixes):
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                await self._reject(send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised inside the app's body read -> FastAPI turns it into
                    # the 413 response (its body parser re-raises HTTPException).
                    raise HTTPException(status_code=413, detail="request body too large")
            return message

        await self.app(scope, limited_receive, send)


def build_csp(nonce: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        )
    )


PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
    "accelerometer=(), gyroscope=(), magnetometer=()"
)


class SecurityHeadersMiddleware:
    """Security headers on every HTTP response (SEC-014)."""

    def __init__(self, app: ASGIApp, *, hsts_max_age: int = 31536000) -> None:
        self.app = app
        self.hsts_max_age = hsts_max_age

    def _is_https(self, scope: Scope) -> bool:
        if scope.get("scheme") == "https":
            return True
        fwd = _header(scope, b"x-forwarded-proto") or ""
        return fwd.split(",")[0].strip().lower() == "https"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        path = scope.get("path", "")
        add_csp = not _path_protected(path, _CSP_EXEMPT_PREFIXES)
        add_hsts = self.hsts_max_age > 0 and self._is_https(scope)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}

                def put(name: str, value: str) -> None:
                    key = name.encode("latin-1")
                    if key not in present:
                        headers.append((key, value.encode("latin-1")))

                if add_csp:
                    put("content-security-policy", build_csp(nonce))
                put("x-frame-options", "DENY")
                put("x-content-type-options", "nosniff")
                put("referrer-policy", "strict-origin-when-cross-origin")
                put("permissions-policy", PERMISSIONS_POLICY)
                if add_hsts:
                    put("strict-transport-security", f"max-age={self.hsts_max_age}")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
