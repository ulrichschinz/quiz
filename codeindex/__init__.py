"""codeindex — a repository-owned, queryable model of THIS codebase.

Pillars 8 (THE INDEX) and 9 (THE INDEX LIFECYCLE) of ``software-repo-prompt.md``:
a stdlib-only, agent-agnostic index over ``app/`` (and ``templates/``) that
answers — for any agent arriving cold —

  * "where is X"            -> :func:`codeindex.query.where`
  * "who imports/uses X"    -> :func:`codeindex.query.who_imports` / ``uses``
  * "what breaks if I change X" -> :func:`codeindex.query.impact`
  * "where do we already do this" -> :func:`codeindex.query.search`

Reachable two ways so it does not depend on any one agent's plugins:
a CLI (``python -m codeindex``) and a thin stdio MCP server
(``codeindex.mcp_server``). The built artifact lives under ``.code-index/`` and
is gitignored — only the tooling is checked in; the index self-heals on query.

Pure standard library (ast, sqlite3, hashlib, json) — same discipline as
``scripts/check_contract.py``. No third-party imports in the core.
"""

from __future__ import annotations

from pathlib import Path

# Repo root = parent of this package directory (…/quiz/codeindex/ -> …/quiz/).
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / ".code-index"
DB_PATH = DB_DIR / "index.db"

# What the index covers. Kept deliberately narrow: the Soll-surface an agent
# reasons about (app/ + the templates it renders). Mirrors check_contract.py.
SOURCE_ROOTS = ("app",)
TEMPLATE_ROOT = "templates"

__all__ = ["REPO_ROOT", "DB_DIR", "DB_PATH", "SOURCE_ROOTS", "TEMPLATE_ROOT"]
