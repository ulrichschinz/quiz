"""app.core.errors — application exception types.

`NeedsLoginException` is raised by the `require_admin` dependency when no admin
session is present; `app/main.py` maps it to a 303 redirect to /login.
"""

from __future__ import annotations


class NeedsLoginException(Exception):
    """No authenticated admin session — redirect to the login page."""
