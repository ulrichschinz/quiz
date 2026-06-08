"""Read-side queries over the index. Pure functions on an open connection so
the CLI and the MCP server share identical behaviour.

Each function returns plain dict/list structures; formatting (human text vs
JSON vs MCP tool result) is the caller's job.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import REPO_ROOT
from .store import meta


def _module_from_target(target: str, repo: Path = REPO_ROOT) -> str:
    """Accept a dotted module, a repo path, or a file path; return dotted module."""
    t = target.strip()
    if t.endswith(".py") or "/" in t:
        p = Path(t)
        if p.is_absolute():
            p = p.relative_to(repo)
        parts = list(p.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)
    return t


def where(conn: sqlite3.Connection, name: str) -> list[dict]:
    """All definitions of ``name`` (bare name or trailing qualname match)."""
    rows = conn.execute(
        """SELECT name, qualname, kind, module, path, lineno, signature, doc
           FROM symbols
           WHERE name = ? OR qualname = ? OR qualname LIKE ?
           ORDER BY kind, path, lineno""",
        (name, name, f"%.{name}"),
    ).fetchall()
    return [dict(r) for r in rows]


def who_imports(conn: sqlite3.Connection, module: str, repo: Path = REPO_ROOT) -> list[dict]:
    """Modules that directly import ``module`` (or a submodule of it)."""
    mod = _module_from_target(module, repo)
    rows = conn.execute(
        """SELECT DISTINCT src, dst, lineno, raw FROM imports
           WHERE external = 0 AND (dst = ? OR dst LIKE ?)
           ORDER BY src""",
        (mod, f"{mod}.%"),
    ).fetchall()
    return [dict(r) for r in rows]


def _reverse_adjacency(conn: sqlite3.Connection) -> dict[str, set[str]]:
    rev: dict[str, set[str]] = {}
    for r in conn.execute("SELECT src, dst FROM imports WHERE external = 0"):
        rev.setdefault(r["dst"], set()).add(r["src"])
    return rev


def impact(conn: sqlite3.Connection, target: str, repo: Path = REPO_ROOT) -> dict:
    """Transitive reverse-import closure: what (might) break if ``target`` changes."""
    mod = _module_from_target(target, repo)
    rev = _reverse_adjacency(conn)
    # A module is affected if it imports `mod` or any of `mod`'s submodules.
    seeds = {m for m in rev if m == mod or m.startswith(mod + ".")}
    affected: set[str] = set()
    frontier = set(seeds)
    while frontier:
        nxt: set[str] = set()
        for m in frontier:
            for importer in rev.get(m, ()):  # noqa: SIM118 - set, not dict
                if importer not in affected and importer != mod:
                    affected.add(importer)
                    nxt.add(importer)
        frontier = nxt
    direct = sorted({i["src"] for i in who_imports(conn, mod, repo)})
    return {"target": mod, "direct": direct, "transitive": sorted(affected)}


def search(conn: sqlite3.Connection, q: str, limit: int = 25) -> list[dict]:
    """Lexical search over symbols/endpoints/tables/templates (FTS5 or LIKE)."""
    mode = meta(conn).get("fts", "like")
    tokens = re.findall(r"\w+", q)
    if mode == "fts5" and tokens:
        match = " ".join(tokens)
        try:
            rows = conn.execute(
                """SELECT kind, name, ref, body FROM search_fts
                   WHERE search_fts MATCH ? ORDER BY rank LIMIT ?""",
                (match, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            pass  # malformed MATCH -> fall through to LIKE
    like = f"%{q}%"
    rows = conn.execute(
        """SELECT kind, name, ref, body FROM search_fts
           WHERE name LIKE ? OR body LIKE ? LIMIT ?""",
        (like, like, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def uses(conn: sqlite3.Connection, name: str, repo: Path = REPO_ROOT) -> dict:
    """Best-effort "who uses X": exact import edges + lexical hits.

    Import edges are precise. Call/attribute usage needs type inference we do
    not do, so the lexical hits are explicitly best-effort, never authoritative.
    """
    modules = sorted({r["module"] for r in where(conn, name)})
    importers: list[dict] = []
    for mod in modules or [name]:
        importers += who_imports(conn, mod, repo)
    uniq = list({(i["src"], i["dst"], i["lineno"]): i for i in importers}.values())
    # Prefer edges whose import line actually names the symbol (precise);
    # fall back to all module importers when the name never appears verbatim.
    precise = [i for i in uniq if name in i["raw"]]
    imported_by = precise if precise else uniq
    return {
        "name": name,
        "imported_by": sorted(imported_by, key=lambda i: (i["src"], i["lineno"])),
        "lexical": search(conn, name),
    }


def status(conn: sqlite3.Connection) -> dict:
    m = meta(conn)
    return {
        "built_at": m.get("built_at", ""),
        "fingerprint": m.get("fingerprint", "")[:12],
        "search": m.get("fts", ""),
        "symbols": int(m.get("n_symbols", 0)),
        "imports": int(m.get("n_imports", 0)),
        "endpoints": int(m.get("n_endpoints", 0)),
        "tables": int(m.get("n_tables", 0)),
        "templates": int(m.get("n_templates", 0)),
    }
