# AGENTS.md

This repository's agent contract lives in **[CLAUDE.md](./CLAUDE.md)** — read it
first. It is the single source of truth for the organizing principle, the
allowed-dependency rules, the "where does a change of kind X go" decision
procedure, the edit order within a unit, and how to run the acceptance gate.

The contract is kept honest by an executable self-check:

```
python scripts/check_contract.py     # asserts ARCHITECTURE.md vs. the code
```

It runs as the `doc-gate` step of `make verify`. If you change structure
(add a domain, route, table or template), update `ARCHITECTURE.md` in the same
change or the gate goes red.

## Navigate with the code index first

Before grepping the tree, ask the repo-owned index (stdlib, no setup):

```
make index-q Q="lead pipeline"          # where do we already do this
python -m codeindex where score_submission   # where is X defined
python -m codeindex uses get_session         # who imports/uses X
python -m codeindex impact app/domains/quizzes/models.py  # what breaks if X changes
```

It self-heals on query and prints a freshness banner. MCP-native agents can
register the same queries as tools via `python -m codeindex.mcp_server` (see
`ARCHITECTURE.md` → Code-Index). It is agent-agnostic by design — the CLI needs
nothing but a shell.
