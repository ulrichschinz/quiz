"""Index lifecycle (pillar 9): detect staleness and self-heal on query.

The build stores a fingerprint of every indexed file. Before answering, we
recompute it cheaply; if it differs (or the DB is missing), we rebuild. Every
answer therefore carries an honest freshness signal.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import DB_PATH, REPO_ROOT
from .build import (
    _fingerprint,  # shared fingerprint algorithm
    build_index,
    iter_source_files,
    iter_template_files,
)
from .store import connect, meta, write


@dataclass(frozen=True)
class Freshness:
    state: str  # "fresh" | "rebuilt" | "built"
    built_at: str
    n_symbols: int
    fts: str

    def banner(self) -> str:
        verb = {"fresh": "FRESH", "rebuilt": "STALE → rebuilt", "built": "built"}[self.state]
        return f"# index: {verb} ({self.n_symbols} symbols, {self.built_at}, search={self.fts})"


def current_fingerprint(repo: Path = REPO_ROOT) -> str:
    return _fingerprint(iter_source_files(repo) + iter_template_files(repo))


def is_stale(conn: sqlite3.Connection, repo: Path = REPO_ROOT) -> bool:
    return meta(conn).get("fingerprint") != current_fingerprint(repo)


def build(repo: Path = REPO_ROOT, db_path: Path = DB_PATH) -> None:
    write(build_index(repo), db_path)


def ensure_fresh(
    repo: Path = REPO_ROOT, db_path: Path = DB_PATH
) -> tuple[sqlite3.Connection, Freshness]:
    """Return an open connection to a guaranteed-fresh index, rebuilding if needed."""
    existed = db_path.exists()
    if not existed:
        build(repo, db_path)
        conn = connect(db_path)
        m = meta(conn)
        return conn, Freshness("built", m["built_at"], int(m["n_symbols"]), m["fts"])

    conn = connect(db_path)
    if is_stale(conn, repo):
        conn.close()
        build(repo, db_path)
        conn = connect(db_path)
        m = meta(conn)
        return conn, Freshness("rebuilt", m["built_at"], int(m["n_symbols"]), m["fts"])

    m = meta(conn)
    return conn, Freshness("fresh", m["built_at"], int(m["n_symbols"]), m["fts"])
