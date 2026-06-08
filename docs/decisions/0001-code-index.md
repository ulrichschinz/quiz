# 0001 — A repo-owned, agent-agnostic code index

**Date:** 2026-06-08
**Status:** accepted

## Context

`software-repo-prompt.md` requires every repo built under it to own pillars 8
(THE INDEX) and 9 (THE INDEX LIFECYCLE): a queryable model of the code, exposed
over a standard protocol so it is **agent-agnostic**, kept fresh automatically.
This repo (MODE C / TUNE — already cleanly structured, green gate, current
contract) had every pillar *except* the index. The sibling
`agentic-reach-ontology-mcp` is an unrelated service and does not cover this
repo; each repo carries its own index.

## Decision

A stdlib-only `codeindex/` package (top-level, beside `scripts/`), exposed two
ways: a CLI (`python -m codeindex …`) for any agent with a shell, and a thin
stdio MCP server (`codeindex/mcp_server.py`) for MCP-native agents.

- **Search backend = SQLite FTS5 (lexical), not embeddings.** For ~2,300 LOC,
  lexical search over symbol names / signatures / docstrings / paths answers
  "where do we already do this" well, stays offline, needs no API key, and keeps
  the acceptance gate hermetic. A true embeddings backend can later slot in
  behind `query.search` without touching callers. (Pillar 8c, pragmatically.)
- **Tooling outside `app/`.** Keeps it clear of the import-linter contracts
  (`root_packages = ["app"]`) and the ARCHITECTURE.md Kennzahlen (which count
  `app/` + `templates/`). Same discipline as `scripts/check_contract.py`.
- **Built artifact (`.code-index/`) is gitignored; only tooling is checked in.**
  The index self-heals on query (rebuild when the file fingerprint changes), so
  there is no stale committed artifact and no index churn in git. Git hooks
  (`make index-hooks`) additionally rebuild on pull/checkout.
- **MCP SDK is an optional pin** (`requirements-mcp.txt`, `mcp==1.27.2`), not in
  `requirements-dev.txt`, so `make verify` / `dev-install` stay hermetic and the
  core has zero third-party dependencies.

## Edges left deliberately EMPTY (never guessed)

Static analysis cannot resolve these, so the index does not emit them: dynamic
domain auto-discovery / `api.register` in `app/main.py`, dependency-injection
wiring, reflection, and Jinja template → route relationships. The import graph
and symbol table are exact; symbol-level "uses" beyond import edges is marked
best-effort (lexical).

## Consequences

- The next agent arriving cold runs `make index-q Q="…"` / `python -m codeindex
  where|uses|impact|search` (or the MCP tools) to navigate before reading files.
- `make verify` gains the `codeindex` lint surface and `tests/unit/test_codeindex.py`
  (hermetic), but the doc-gate counts are unchanged.
- Revisit the embeddings backend if lexical search proves insufficient as the
  codebase grows.
