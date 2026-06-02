# Use the venv interpreter directly so `make` works without activating it.
# CI runs `make PY=python ...` (deps installed into the runner's system py).
PY ?= .venv/bin/python
# import-linter ships only a console script (no `python -m` entrypoint).
LINT_IMPORTS ?= .venv/bin/lint-imports

.PHONY: help install dev-install verify lint format-check fmt typecheck contracts doc-gate test test-fast test-e2e new-quiz seed clean

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

install:
	$(PY) -m pip install -r requirements.txt

dev-install:
	$(PY) -m pip install -r requirements-dev.txt

# THE acceptance gate. A green run == mergeable.
verify: lint format-check typecheck contracts test-fast doc-gate

lint:
	$(PY) -m ruff check scripts app

format-check:
	$(PY) -m ruff format --check scripts app

fmt:
	$(PY) -m ruff format scripts app

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

clean:
	rm -rf .pytest_cache __pycache__ */__pycache__ .coverage reports
	find . -name '*.pyc' -delete
