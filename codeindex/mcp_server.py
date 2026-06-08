"""Thin stdio MCP server exposing the code index as agent-native tools.

This is a *wrapper*: all logic lives in :mod:`codeindex.query` and
:mod:`codeindex.freshness`, identical to the CLI. It exists so MCP-capable
agents (Claude Code, Cursor, …) get ``where/uses/impact/search/status`` as
first-class tools — while the CLI keeps the index usable for any agent without
MCP.

Run:  ``python -m codeindex.mcp_server``   (requires the ``mcp`` package — a
dev/tooling dependency, see requirements-dev.txt). The core index has NO
third-party dependency; only this entrypoint does, and it imports ``mcp`` lazily
so importing the package never forces it.

Register in ``.mcp.json`` (project scope):

    {
      "mcpServers": {
        "codeindex": { "command": "python", "args": ["-m", "codeindex.mcp_server"] }
      }
    }
"""

from __future__ import annotations

from . import query
from .freshness import ensure_fresh


def _with_index(fn):
    """Open a fresh index, run ``fn(conn)``, attach the freshness banner."""
    conn, fresh = ensure_fresh()
    try:
        result = fn(conn)
    finally:
        conn.close()
    return {"index": fresh.banner(), "result": result}


def build_server():  # pragma: no cover - exercised only when `mcp` is installed
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("codeindex")

    @server.tool()
    def where(name: str) -> dict:
        """Where is a symbol (function/class/method/module) defined? -> file:line list."""
        return _with_index(lambda c: query.where(c, name))

    @server.tool()
    def uses(name: str) -> dict:
        """Who imports/uses a symbol. Import edges are precise; lexical hits best-effort."""
        return _with_index(lambda c: query.uses(c, name))

    @server.tool()
    def who_imports(module: str) -> dict:
        """Which modules directly import the given module (or a submodule)."""
        return _with_index(lambda c: query.who_imports(c, module))

    @server.tool()
    def impact(target: str) -> dict:
        """What breaks if a module/file changes — transitive reverse-import closure."""
        return _with_index(lambda c: query.impact(c, target))

    @server.tool()
    def search(q: str, limit: int = 25) -> dict:
        """Lexical search across symbols/endpoints/tables/templates ("where do we already do this")."""
        return _with_index(lambda c: query.search(c, q, limit))

    @server.tool()
    def status() -> dict:
        """Index freshness and counts."""
        return _with_index(query.status)

    return server


def main() -> None:  # pragma: no cover
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
