"""app.core.security — admin authentication helpers.

Single-admin model: there is no user table. The admin password lives in the
`ADMIN_PASSWORD` env var; login compares the submitted value in constant time
and, on success, marks the session. `require_admin` is the route dependency
that gates the admin area.
"""

from __future__ import annotations

import secrets

from fastapi import Request

from app.core.errors import NeedsLoginException

SESSION_ADMIN_KEY = "admin"


def verify_admin_password(submitted: str, expected: str | None) -> bool:
    """Constant-time compare of a submitted password against the configured one.

    Returns False when no admin password is configured (admin area disabled).
    """
    if not expected:
        return False
    return secrets.compare_digest(submitted, expected)


def require_admin(request: Request) -> None:
    """Route dependency: raise NeedsLoginException unless an admin is logged in."""
    if not request.session.get(SESSION_ADMIN_KEY):
        raise NeedsLoginException()
