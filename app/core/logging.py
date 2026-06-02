"""app.core.logging — thin stdlib logging accessor.

A single helper so call sites don't reach for `logging.getLogger` directly and
the logger namespace stays consistent (`quiz.<module>`).
"""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"quiz.{name}")
