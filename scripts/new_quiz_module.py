#!/usr/bin/env python3
"""Scaffold a new domain package — the one-command anti-"random files" step.

`make new-quiz X` emits a domain skeleton (models/schemas/service) plus a green
service-level smoke test, import-linter- and ruff-format-conformant *by
construction* (zero manual edits -> gate green). It also patches the
import-linter `independence` contract in pyproject.toml so the new domain is
enforced from commit one (no manual post-step).

Lives in scripts/ (dev tooling), so generating a domain never moves the
ARCHITECTURE.md Kennzahlen until the result is committed.

Usage:
    python scripts/new_quiz_module.py <name> [--force]
    make new-quiz <name>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
PYPROJECT = REPO / "pyproject.toml"

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _class_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _write(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite existing file: {path.relative_to(REPO)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path.relative_to(REPO)}")


def _patch_independence_contract(name: str) -> bool:
    """Insert ``"app.domains.<name>",`` into the independence-contract modules
    array of pyproject.toml. No-op when already present or the block is absent.
    """
    if not PYPROJECT.exists():
        return False
    target = f'"app.domains.{name}"'
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines(keepends=True)

    in_contract = is_independence = in_modules = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[[tool.importlinter.contracts]]":
            in_contract, is_independence, in_modules = True, False, False
            continue
        if not in_contract:
            continue
        if stripped.startswith("["):
            in_contract = stripped == "[[tool.importlinter.contracts]]"
            is_independence = in_modules = False
            continue
        if stripped == 'type = "independence"':
            is_independence = True
            continue
        if is_independence and stripped.startswith("modules"):
            in_modules = True
            continue
        if in_modules:
            if target in line:
                return False
            if stripped == "]":
                lines.insert(idx, f"    {target},\n")
                PYPROJECT.write_text("".join(lines), encoding="utf-8")
                print(f"  patched pyproject.toml (independence += {target})")
                return True
    return False


def _models(name: str, cls: str) -> str:
    return f'''\
"""{cls} domain — SQLModel tables. Replace the starter with the real shape."""

from __future__ import annotations

from sqlmodel import Field

from app.core.db import SQLModel


class {cls}(SQLModel, table=True):
    """Minimal starter table — replace with the real {name} shape."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
'''


def _schemas(cls: str) -> str:
    return f'''\
"""{cls} domain — Pydantic API schemas (no ORM, no FastAPI import)."""

from __future__ import annotations

from pydantic import BaseModel


class {cls}Create(BaseModel):
    name: str


class {cls}Read(BaseModel):
    id: int
    name: str
'''


def _service(name: str, cls: str) -> str:
    return f'''\
"""{cls} domain — business logic. Session passed in by the interface layer."""

from __future__ import annotations

from sqlmodel import Session, select

from app.domains.{name}.models import {cls}
from app.domains.{name}.schemas import {cls}Create


def create_{name}(session: Session, data: {cls}Create) -> {cls}:
    obj = {cls}(name=data.name)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def list_{name}(session: Session) -> list[{cls}]:
    return list(session.exec(select({cls})).all())
'''


def _test(name: str, cls: str) -> str:
    return f'''\
"""Smoke test for the {name} domain scaffold — green with zero manual edits."""

from __future__ import annotations

from sqlmodel import Session, create_engine

from app.core.db import SQLModel
from app.domains.{name} import service
from app.domains.{name}.schemas import {cls}Create


def test_{name}_create_and_list_roundtrip() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        created = service.create_{name}(session, {cls}Create(name="smoke"))
        assert created.id is not None
        rows = service.list_{name}(session)
    assert [r.name for r in rows] == ["smoke"]
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="new-quiz", description=__doc__)
    parser.add_argument("name", help="domain name (lowercase, snake_case)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing domain")
    args = parser.parse_args(argv)

    name: str = args.name
    if not _NAME_RE.match(name):
        print(
            f"error: invalid domain name {name!r} — must match {_NAME_RE.pattern}", file=sys.stderr
        )
        return 2

    cls = _class_name(name)
    domain_dir = APP / "domains" / name
    if domain_dir.exists() and not args.force:
        print(f"error: domain {name!r} already exists (use --force)", file=sys.stderr)
        return 2

    print(f"scaffolding domain {name!r} (class {cls}):")
    _write(domain_dir / "__init__.py", f'"""{cls} domain package."""\n', force=args.force)
    _write(domain_dir / "models.py", _models(name, cls), force=args.force)
    _write(domain_dir / "schemas.py", _schemas(cls), force=args.force)
    _write(domain_dir / "service.py", _service(name, cls), force=args.force)
    _write(REPO / "tests" / "unit" / f"test_{name}.py", _test(name, cls), force=args.force)
    _patch_independence_contract(name)

    print("done. Edit order: models -> schemas -> service. Verify with `make verify`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
