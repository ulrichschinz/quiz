"""app.shared.clock — single source for timestamp defaults.

`utcnow()` returns a naive UTC datetime (tz stripped) so stored stamps stay
comparable with values read back from SQLite, without the `datetime.utcnow()`
deprecation.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
