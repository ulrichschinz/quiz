# Use the venv interpreter directly so `make` works without activating it.
# CI runs `make PY=python ...` (deps installed into the runner's system py).
PY ?= .venv/bin/python
# import-linter ships only a console script (no `python -m` entrypoint).
LINT_IMPORTS ?= .venv/bin/lint-imports

.PHONY: help install dev-install verify lint format-check fmt typecheck contracts doc-gate test test-fast test-e2e new-quiz seed clean index index-q index-status index-hooks

help:
	@echo "Agentic Reach Quiz — make targets"
	@echo "  make dev-install      install runtime + dev deps into .venv"
	@echo "  make verify           the gate: lint+format+typecheck+contracts+test-fast+doc-gate"
	@echo "  make lint             ruff lint (app/ + scripts/)"
	@echo "  make format-check     ruff format --check (app/ + scripts/)"
	@echo "  make fmt              ruff format --write"
	@echo "  make typecheck        mypy (app.* strict, lax global)"
	@echo "  make contracts        import-linter (executable import boundaries)"
	@echo "  make doc-gate         assert ARCHITECTURE.md Kennzahlen vs. code"
	@echo "  make new-quiz X       scaffold a new domain (app/domains/X + test)"
	@echo "  make seed             load the flagship quiz into the DB"
	@echo "  make test             full test suite"
	@echo "  make test-fast        unit + integration (skip e2e)"
	@echo "  make test-e2e         end-to-end tests (FastAPI TestClient)"
	@echo "  make index            (re)build the code index (.code-index/)"
	@echo "  make index-q Q=...    query the index (search)"
	@echo "  make index-status     index freshness + counts"
	@echo "  make index-hooks      install git hooks that rebuild on pull/checkout"

install:
	$(PY) -m pip install -r requirements.txt

dev-install:
	$(PY) -m pip install -r requirements-dev.txt

# THE acceptance gate. A green run == mergeable.
verify: lint format-check typecheck contracts test-fast doc-gate

lint:
	$(PY) -m ruff check scripts app codeindex

format-check:
	$(PY) -m ruff format --check scripts app codeindex

fmt:
	$(PY) -m ruff format scripts app codeindex

typecheck:
	$(PY) -m mypy app

contracts:
	$(LINT_IMPORTS)

doc-gate:
	$(PY) scripts/check_contract.py

test:
	$(PY) -m pytest

test-fast:
	$(PY) -m pytest -m "not e2e"

test-e2e:
	$(PY) -m pytest -m e2e

# One-command new domain (the anti-"random files" mechanism).
#   make new-quiz X
new-quiz:
	@test -n "$(filter-out new-quiz,$(MAKECMDGOALS))$(NAME)" || { echo "usage: make new-quiz <name>"; exit 2; }
	$(PY) scripts/new_quiz_module.py $(if $(NAME),$(NAME),$(filter-out new-quiz,$(MAKECMDGOALS)))
%:
	@:

seed:
	PYTHONPATH=. $(PY) scripts/seed_flagship.py

# --- Code index (software-repo-prompt.md pillars 8 + 9) -------------------
# Agent-agnostic: `python -m codeindex <cmd>` works for any agent with a shell;
# the MCP server (codeindex/mcp_server.py) is the native path for MCP agents.
index:
	$(PY) -m codeindex build

index-q:
	@test -n "$(Q)" || { echo 'usage: make index-q Q="<search terms>"'; exit 2; }
	$(PY) -m codeindex search $(Q)

index-status:
	$(PY) -m codeindex status

index-hooks:
	$(PY) -m codeindex install-hooks

clean:
	rm -rf .pytest_cache __pycache__ */__pycache__ .coverage reports
	find . -name '*.pyc' -delete
