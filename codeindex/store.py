"""SQLite persistence for the index, with an FTS5 search table.

FTS5 ships with most CPython builds, but not all — so search degrades
gracefully to a ``LIKE`` scan when the module is missing (kept honest in
``status``). The built database lives under ``.code-index/`` and is gitignored.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import DB_PATH
from .model import IndexData

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE symbols (
    name TEXT, qualname TEXT, kind TEXT, module TEXT, path TEXT,
    lineno INTEGER, end_lineno INTEGER, signature TEXT, doc TEXT, parent TEXT
);
CREATE TABLE imports (
    src TEXT, dst TEXT, lineno INTEGER, raw TEXT, external INTEGER
);
CREATE TABLE endpoints (
    method TEXT, route TEXT, func TEXT, module TEXT, path TEXT, lineno INTEGER
);
CREATE TABLE tables_ (name TEXT, module TEXT, path TEXT, lineno INTEGER);
CREATE TABLE templates (path TEXT);
CREATE INDEX ix_symbols_name ON symbols(name);
CREATE INDEX ix_imports_dst ON imports(dst);
"""


def fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def write(data: IndexData, db_path: Path = DB_PATH) -> None:
    """(Re)create the database from scratch and populate it from ``data``."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        has_fts = fts5_available(conn)
        if has_fts:
            conn.execute("CREATE VIRTUAL TABLE search_fts USING fts5(kind, name, ref, body)")
        else:
            conn.execute("CREATE TABLE search_fts (kind TEXT, name TEXT, ref TEXT, body TEXT)")

        conn.executemany(
            "INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    s.name,
                    s.qualname,
                    s.kind,
                    s.module,
                    s.path,
                    s.lineno,
                    s.end_lineno,
                    s.signature,
                    s.doc,
                    s.parent,
                )
                for s in data.symbols
            ],
        )
        conn.executemany(
            "INSERT INTO imports VALUES (?,?,?,?,?)",
            [(i.src, i.dst, i.lineno, i.raw, int(i.external)) for i in data.imports],
        )
        conn.executemany(
            "INSERT INTO endpoints VALUES (?,?,?,?,?,?)",
            [(e.method, e.route, e.func, e.module, e.path, e.lineno) for e in data.endpoints],
        )
        conn.executemany(
            "INSERT INTO tables_ VALUES (?,?,?,?)",
            [(t.name, t.module, t.path, t.lineno) for t in data.tables],
        )
        conn.executemany("INSERT INTO templates VALUES (?)", [(t.path,) for t in data.templates])

        conn.executemany("INSERT INTO search_fts VALUES (?,?,?,?)", list(_search_rows(data)))

        meta = {
            "fingerprint": data.fingerprint,
            "built_at": data.built_at,
            "fts": "fts5" if has_fts else "like",
            "n_symbols": str(len(data.symbols)),
            "n_imports": str(len(data.imports)),
            "n_endpoints": str(len(data.endpoints)),
            "n_tables": str(len(data.tables)),
            "n_templates": str(len(data.templates)),
        }
        conn.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
        conn.commit()
    finally:
        conn.close()


def _search_rows(data: IndexData):
    for s in data.symbols:
        body = " ".join(filter(None, [s.qualname, s.signature, s.doc, s.path]))
        yield (s.kind, s.name, f"{s.path}:{s.lineno}", body)
    for e in data.endpoints:
        yield (
            "endpoint",
            f"{e.method.upper()} {e.route}".strip(),
            f"{e.path}:{e.lineno}",
            f"{e.method} {e.route} {e.func} {e.module}",
        )
    for t in data.tables:
        yield ("table", t.name, f"{t.path}:{t.lineno}", f"{t.name} {t.module}")
    for tpl in data.templates:
        yield ("template", Path(tpl.path).name, tpl.path, tpl.path)


def meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
