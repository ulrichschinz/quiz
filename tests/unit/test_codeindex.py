"""Unit tests for the code index — hermetic: build against a tiny fixture tree
in tmp_path, never the real repo, so they are fast and deterministic."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeindex import build, freshness, query, store

FILES = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/core/db.py": "def get_session():\n    '''Yield a DB session.'''\n    return None\n",
    "app/domains/__init__.py": "",
    "app/domains/widgets/__init__.py": "",
    "app/domains/widgets/models.py": (
        "from app.core.db import get_session\n\n\n"
        "class Widget(table=True):\n    '''A widget row.'''\n    id: int\n"
    ),
    "app/domains/widgets/service.py": (
        "from app.domains.widgets.models import Widget\n\n\n"
        "def make_widget() -> Widget:\n    '''Create a widget.'''\n    return Widget()\n"
    ),
    "app/interfaces/__init__.py": "",
    "app/interfaces/web.py": (
        "from app.domains.widgets import service\n\nrouter = object()\n\n\n"
        "@router.get('/widgets')\ndef list_widgets():\n    '''List widgets.'''\n    return service\n"
    ),
    "templates/index.html": "<h1>hi</h1>\n",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for rel, content in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.fixture
def conn(repo: Path):
    db = repo / ".code-index" / "index.db"
    store.write(build.build_index(repo), db)
    c = store.connect(db)
    yield c
    c.close()


def test_symbols_classes_functions_modules(conn) -> None:
    rows = query.where(conn, "Widget")
    assert len(rows) == 1
    assert rows[0]["kind"] == "class"
    assert rows[0]["path"] == "app/domains/widgets/models.py"
    assert query.where(conn, "make_widget")[0]["kind"] == "function"
    assert query.where(conn, "get_session")[0]["signature"].startswith("get_session(")


def test_counts_endpoints_and_tables(conn) -> None:
    st = query.status(conn)
    assert st["endpoints"] == 1
    assert st["tables"] == 1
    assert st["templates"] == 1
    assert st["symbols"] > 5


def test_who_imports_resolves_submodule(conn, repo) -> None:
    # `from app.domains.widgets import service` must edge to the SUBMODULE.
    importers = {r["src"] for r in query.who_imports(conn, "app.domains.widgets.service", repo)}
    assert "app.interfaces.web" in importers


def test_impact_transitive_closure(conn, repo) -> None:
    res = query.impact(conn, "app/domains/widgets/models.py", repo)
    assert res["target"] == "app.domains.widgets.models"
    assert "app.domains.widgets.service" in res["direct"]
    # web -> service -> models, so web is transitively affected
    assert "app.interfaces.web" in res["transitive"]


def test_search_finds_by_name_and_doc(conn) -> None:
    hits = {r["name"] for r in query.search(conn, "widget")}
    assert any("idget" in h or "widget" in h.lower() for h in hits)


def test_freshness_self_heals_on_change(repo) -> None:
    db = repo / ".code-index" / "index.db"
    conn, fresh = freshness.ensure_fresh(repo, db)
    assert fresh.state == "built"
    conn.close()

    conn, fresh = freshness.ensure_fresh(repo, db)
    assert fresh.state == "fresh"
    assert not freshness.is_stale(conn, repo)
    conn.close()

    (repo / "app/core/db.py").write_text("def get_session():\n    return 1\n", encoding="utf-8")
    conn, fresh = freshness.ensure_fresh(repo, db)
    assert fresh.state == "rebuilt"
    conn.close()
