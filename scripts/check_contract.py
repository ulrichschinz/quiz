#!/usr/bin/env python3
"""Contract self-check — assert ARCHITECTURE.md claims against the codebase.

The contract (AGENTS.md / CLAUDE.md) is only trustworthy if its factual claims
are CI-verified. This stdlib-only script asserts:

  1. the `## Kennzahlen` table (structural counts) vs. the live code, and
  2. the `## Struktur-Verträge` table (import-linter contract names) vs.
     `pyproject.toml`.

Any drift fails the gate (exit 1) until doc and code agree again. Malformed
table / missing tracked row => exit 2. Lives in scripts/ (dev tooling, never
counted in its own metrics).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARCH = REPO / "ARCHITECTURE.md"
PYPROJECT = REPO / "pyproject.toml"
APP = REPO / "app"

_ENDPOINT_RE = re.compile(r"@router\.(get|post|put|patch|delete)\b")
_TABLE_RE = re.compile(r"^class\s+\w+\(.*\btable=True\b", re.M)


def _app_py_files() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "__pycache__" not in p.parts]


def _route_modules() -> list[Path]:
    out: list[Path] = []
    for d in ("web", "api"):
        out += [p for p in (APP / "interfaces" / d).glob("*.py") if p.name != "__init__.py"]
    out += list(APP.glob("domains/*/router.py"))
    return out


def m_domains() -> int:
    base = APP / "domains"
    return sum(1 for p in base.iterdir() if p.is_dir() and (p / "__init__.py").exists())


def m_route_modules() -> int:
    return len(_route_modules())


def m_endpoints() -> int:
    return sum(len(_ENDPOINT_RE.findall(p.read_text(encoding="utf-8"))) for p in _route_modules())


def m_templates() -> int:
    return len(list((REPO / "templates").rglob("*.html")))


def m_tables() -> int:
    return sum(len(_TABLE_RE.findall(p.read_text(encoding="utf-8"))) for p in _app_py_files())


# Row label in ARCHITECTURE.md  ->  live computation.
METRICS = {
    "Domains": m_domains,
    "Route-Module": m_route_modules,
    "HTTP-Endpoints": m_endpoints,
    "HTML-Templates": m_templates,
    "SQLModel-Tabellen": m_tables,
}


def _table_rows(md: str, heading: str) -> list[list[str]]:
    lines = md.splitlines()
    try:
        start = next(
            i
            for i, ln in enumerate(lines)
            if ln.strip() == heading or ln.strip().startswith(heading + " ")
        )
    except StopIteration:
        print(f"ERROR: '{heading}' heading not found in ARCHITECTURE.md", file=sys.stderr)
        sys.exit(2)
    out: list[list[str]] = []
    for ln in lines[start + 1 :]:
        s = ln.strip()
        if s.startswith("## "):
            break
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        out.append(cells)
    return out


def parse_kennzahlen(md: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for cells in _table_rows(md, "## Kennzahlen"):
        if len(cells) < 2:
            continue
        label = cells[0].replace("`", "")
        if label in ("Metrik", ""):
            continue
        digits = re.search(r"\d+", cells[1].replace(".", ""))
        if digits:
            out[label] = int(digits.group())
    return out


def parse_importlinter_contract_names() -> set[str]:
    text = PYPROJECT.read_text(encoding="utf-8")
    names: set[str] = set()
    in_block = False
    for ln in text.splitlines():
        s = ln.strip()
        if s == "[[tool.importlinter.contracts]]":
            in_block = True
            continue
        if s.startswith("[") and s != "[[tool.importlinter.contracts]]":
            in_block = False
            continue
        if in_block:
            m = re.match(r'^name\s*=\s*"(.+)"\s*$', s)
            if m:
                names.add(m.group(1))
    return names


def parse_documented_contracts(md: str) -> set[str]:
    rows = _table_rows(md, "## Struktur-Verträge")
    return {row[0].strip("`") for row in rows if row and row[0] and row[0] != "Contract"}


def main() -> int:
    md = ARCH.read_text(encoding="utf-8")
    documented = parse_kennzahlen(md)

    rows: list[tuple[str, int, int]] = []
    missing: list[str] = []
    for label, fn in METRICS.items():
        if label not in documented:
            missing.append(label)
            continue
        rows.append((label, documented[label], fn()))

    if missing:
        print("ERROR: tracked metric(s) absent from Kennzahlen table:", file=sys.stderr)
        for label in missing:
            print(f"  - {label}", file=sys.stderr)
        return 2

    width = max(len(r[0]) for r in rows)
    print(f"{'Metric'.ljust(width)}  {'doc':>5}  {'code':>5}  ok")
    print("-" * (width + 20))
    drift: list[tuple[str, int, int]] = []
    for label, expected, actual in rows:
        ok = expected == actual
        print(f"{label.ljust(width)}  {expected:>5}  {actual:>5}  {'OK' if ok else 'DRIFT'}")
        if not ok:
            drift.append((label, expected, actual))

    code_contracts = parse_importlinter_contract_names()
    doc_contracts = parse_documented_contracts(md)
    contract_drift = sorted(doc_contracts ^ code_contracts)

    if drift or contract_drift:
        print(file=sys.stderr)
        for label, expected, actual in drift:
            print(
                f"  Kennzahl '{label}': doc says {expected}, code has {actual} "
                f"(fix the code OR update ARCHITECTURE.md — they must agree)",
                file=sys.stderr,
            )
        for name in contract_drift:
            where = "pyproject.toml" if name in code_contracts else "ARCHITECTURE.md"
            print(f"  import-linter contract only in {where}: {name!r}", file=sys.stderr)
        return 1

    print(
        f"\nAll {len(rows)} Kennzahlen match the code "
        f"({len(code_contracts)} import-linter contracts accounted for)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
