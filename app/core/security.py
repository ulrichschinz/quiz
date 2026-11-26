"""app.core.security — admin authentication helpers.

Single-admin model: there is no user table. The admin password lives in the
`ADMIN_PASSWORD` env var; login compares the submitted value in constant time
and, on success, starts an admin session. `require_admin` is the route
dependency that gates the admin area.

Session revocation (SEC-006). The Starlette session is a signed, client-side
cookie, so on its own it cannot be revoked. An admin session therefore carries

* a random session id (`sid`) that must be present in the in-process
  `admin_sessions` registry (allow-list with an absolute expiry). Logout removes
  it, so a copied cookie is dead after logout; a process restart empties the
  registry, which logs every admin out (fail-closed: a restart never revives a
  revoked cookie, unlike an in-memory deny-list would);
* a password fingerprint (HMAC-SHA256 of `ADMIN_PASSWORD` keyed with
  `SECRET_KEY`, truncated). Changing either value invalidates all sessions.

Brute-force protection (SEC-007): `login_throttle` counts failed logins per
client key (IP) in a sliding window and blocks further attempts once the limit
is reached.

Both registries are in-memory and guarded by a lock. They assume the app runs
as ONE process (a single uvicorn worker, as deployed). With several workers or
replicas each process would have its own registry (sessions would randomly
appear logged out and the throttle limit would multiply) — move them to the DB
or a shared store before scaling out.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import NeedsLoginException

SESSION_ADMIN_KEY = "admin"
SESSION_ID_KEY = "admin_sid"
SESSION_FINGERPRINT_KEY = "admin_fp"


def verify_admin_password(submitted: str, expected: str | None) -> bool:
    """Constant-time compare of a submitted password against the configured one.

    Returns False when no admin password is configured (admin area disabled).
    Compares UTF-8 bytes so non-ASCII input/passwords work (SEC-013).
    """
    if not expected:
        return False
    return secrets.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))


def password_fingerprint(admin_password: str | None, secret_key: str) -> str | None:
    """HMAC(secret_key, admin_password), truncated. None if no password is set."""
    if not admin_password:
        return None
    digest = hmac.new(
        secret_key.encode("utf-8"), admin_password.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return digest[:32]


class AdminSessionRegistry:
    """Thread-safe allow-list of live admin session ids with absolute expiry."""

    def __init__(
        self, max_entries: int = 1000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}  # sid -> expires_at (clock time)
        self._max_entries = max_entries
        self._clock = clock

    def issue(self, ttl_seconds: int) -> str:
        sid = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            self._prune(now)
            while len(self._sessions) >= self._max_entries:
                # Evict the oldest login (dicts keep insertion order).
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[sid] = now + ttl_seconds
        return sid

    def is_active(self, sid: str) -> bool:
        now = self._clock()
        with self._lock:
            expires_at = self._sessions.get(sid)
            if expires_at is None:
                return False
            if expires_at <= now:
                del self._sessions[sid]
                return False
            return True

    def revoke(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def revoke_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _prune(self, now: float) -> None:
        for sid in [s for s, exp in self._sessions.items() if exp <= now]:
            del self._sessions[sid]


class LoginThrottle:
    """Thread-safe sliding-window counter of failed logins per client key."""

    def __init__(self, max_keys: int = 10_000, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}
        self._max_keys = max_keys
        self._clock = clock

    def retry_after(self, key: str, max_failures: int, window_seconds: int) -> int:
        """Seconds until `key` may try again; 0 if it is not blocked."""
        now = self._clock()
        with self._lock:
            q = self._failures.get(key)
            if q is None:
                return 0
            self._expire(q, now, window_seconds)
            if not q:
                del self._failures[key]
                return 0
            if len(q) < max_failures:
                return 0
            # Blocked until enough old failures slide out of the window.
            unblock_at = q[len(q) - max_failures] + window_seconds
            return max(1, int(unblock_at - now + 0.999))

    def record_failure(self, key: str, window_seconds: int) -> None:
        now = self._clock()
        with self._lock:
            q = self._failures.get(key)
            if q is None:
                if len(self._failures) >= self._max_keys:
                    self._prune(now, window_seconds)
                    while len(self._failures) >= self._max_keys:
                        self._failures.pop(next(iter(self._failures)))
                q = self._failures[key] = deque()
            self._expire(q, now, window_seconds)
            q.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()

    @staticmethod
    def _expire(q: deque[float], now: float, window_seconds: int) -> None:
        while q and q[0] <= now - window_seconds:
            q.popleft()

    def _prune(self, now: float, window_seconds: int) -> None:
        for key in list(self._failures):
            q = self._failures[key]
            self._expire(q, now, window_seconds)
            if not q:
                del self._failures[key]


admin_sessions = AdminSessionRegistry()
login_throttle = LoginThrottle()


def client_key(request: Request) -> str:
    """Throttle key for a request: the peer IP as uvicorn reports it.

    X-Forwarded-For is deliberately NOT parsed here. uvicorn's proxy-headers
    handling rewrites `request.client` from X-Forwarded-For only for peers
    listed in FORWARDED_ALLOW_IPS (default 127.0.0.1), so the value is only as
    trustworthy as that setting — a client cannot spoof it from outside.
    """
    return request.client.host if request.client else "unknown"


def start_admin_session(request: Request) -> None:
    """Mark the session as admin (after a successful password check)."""
    settings = get_settings()
    request.session.clear()  # drop anything pre-login (no fixation carry-over)
    request.session[SESSION_ADMIN_KEY] = True
    request.session[SESSION_ID_KEY] = admin_sessions.issue(settings.session_max_age)
    request.session[SESSION_FINGERPRINT_KEY] = password_fingerprint(
        settings.admin_password, settings.secret_key
    )


def end_admin_session(request: Request) -> None:
    """Logout: revoke the session id server-side and clear the cookie."""
    sid = request.session.get(SESSION_ID_KEY)
    if isinstance(sid, str):
        admin_sessions.revoke(sid)
    request.session.clear()


def is_admin(request: Request) -> bool:
    """True iff the request carries a live, non-revoked admin session."""
    session = request.session
    if session.get(SESSION_ADMIN_KEY) is not True:
        return False
    sid = session.get(SESSION_ID_KEY)
    fp = session.get(SESSION_FINGERPRINT_KEY)
    if not isinstance(sid, str) or not isinstance(fp, str):
        return False
    settings = get_settings()
    expected = password_fingerprint(settings.admin_password, settings.secret_key)
    if expected is None or not hmac.compare_digest(fp.encode("utf-8"), expected.encode("utf-8")):
        return False
    return admin_sessions.is_active(sid)


def require_admin(request: Request) -> None:
    """Route dependency: raise NeedsLoginException unless an admin is logged in."""
    if not is_admin(request):
        if request.session:
            request.session.clear()
        raise NeedsLoginException()
