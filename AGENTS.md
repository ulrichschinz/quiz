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
