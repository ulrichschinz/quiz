"""Table registry — import every domain's models so SQLModel.metadata is complete.

Importing this module registers all tables on the shared `SQLModel.metadata`.
The Alembic baseline and the test fixtures import it before `create_all` /
`create_db` so the metadata sees every domain table exactly once. It lives
outside `app.core` on purpose: the kernel must stay domain-agnostic
(import-linter), so the composition that knows the full table set lives here.
"""

from __future__ import annotations

from app.domains.quizzes import models as _quizzes_models  # noqa: F401
from app.domains.submissions import models as _submissions_models  # noqa: F401


def register_tables() -> None:
    """No-op marker: importing this module already registered the tables."""
