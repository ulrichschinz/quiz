"""``python -m codeindex`` — the agent-agnostic interface.

Any agent with a shell can use this; no MCP, no plugin required. Every query
self-heals the index first and prints a freshness banner (pillar 9), then the
result as human text (default) or ``--json``.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys

from . import REPO_ROOT, query
from .freshness import build, ensure_fresh

_HOOK = """#!/bin/sh
# Auto-installed by `make index-hooks` — keep the code index fresh on pull/checkout.
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
"$PY" -m codeindex build >/dev/null 2>&1 || true
"""


def _install_hooks() -> int:
    hooks_dir = REPO_ROOT / ".git" / "hooks"
    if not hooks_dir.exists():
        print("  no .git/hooks — not a git checkout?", file=sys.stderr)
        return 1
    for name in ("post-merge", "post-checkout"):
        path = hooks_dir / name
        path.write_text(_HOOK, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  installed {path.relative_to(REPO_ROOT)}")
    return 0


def _emit(obj: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))


def _fmt_symbol(r: dict) -> str:
    sig = f" {r['signature']}" if r.get("signature") else ""
    doc = f"  — {r['doc']}" if r.get("doc") else ""
    return f"  {r['path']}:{r['lineno']}  [{r['kind']}] {r['qualname']}{sig}{doc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codeindex", description="Query the repository code index."
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build", help="(re)build the index now")
    sub.add_parser("install-hooks", help="install git hooks that rebuild on pull/checkout")
    sub.add_parser("status", help="freshness + counts")
    p_where = sub.add_parser("where", help="where is a symbol defined")
    p_where.add_argument("name")
    p_uses = sub.add_parser("uses", help="who imports/uses a symbol or module")
    p_uses.add_argument("name")
    p_imports = sub.add_parser("who-imports", help="modules importing a module")
    p_imports.add_argument("module")
    p_impact = sub.add_parser("impact", help="what breaks if a module/file changes")
    p_impact.add_argument("target")
    p_search = sub.add_parser("search", help="lexical search across the codebase")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=25)

    args = parser.parse_args(argv)
    as_json = args.json

    if args.cmd == "install-hooks":
        return _install_hooks()

    if args.cmd == "build":
        build()
        conn, fresh = ensure_fresh()
        st = query.status(conn)
        conn.close()
        if as_json:
            _emit({"freshness": fresh.state, **st}, True)
        else:
            print(fresh.banner())
            print("Index built.")
        return 0

    conn, fresh = ensure_fresh()
    try:
        if args.cmd == "status":
            st = query.status(conn)
            if as_json:
                _emit({"freshness": fresh.state, **st}, True)
            else:
                print(fresh.banner())
                for k, v in st.items():
                    print(f"  {k:<12} {v}")
            return 0

        if args.cmd == "where":
            rows = query.where(conn, args.name)
            if as_json:
                _emit({"banner": fresh.banner(), "results": rows}, True)
            else:
                print(fresh.banner())
                if not rows:
                    print(f"  no symbol named {args.name!r}")
                for r in rows:
                    print(_fmt_symbol(r))
            return 0 if rows else 1

        if args.cmd == "who-imports":
            rows = query.who_imports(conn, args.module)
            if as_json:
                _emit({"banner": fresh.banner(), "results": rows}, True)
            else:
                print(fresh.banner())
                for r in rows:
                    print(f"  {r['src']}  (line {r['lineno']}): {r['raw']}")
                if not rows:
                    print(f"  nothing imports {args.module!r}")
            return 0

        if args.cmd == "uses":
            res = query.uses(conn, args.name)
            if as_json:
                _emit({"banner": fresh.banner(), **res}, True)
            else:
                print(fresh.banner())
                print(f"  imported_by ({len(res['imported_by'])}):")
                for r in res["imported_by"]:
                    print(f"    {r['src']}  (line {r['lineno']})")
                print(f"  lexical hits ({len(res['lexical'])}, best-effort):")
                for r in res["lexical"][:15]:
                    print(f"    {r['ref']}  [{r['kind']}] {r['name']}")
            return 0

        if args.cmd == "impact":
            res = query.impact(conn, args.target)
            if as_json:
                _emit({"banner": fresh.banner(), **res}, True)
            else:
                print(fresh.banner())
                print(f"  target: {res['target']}")
                print(f"  direct importers ({len(res['direct'])}):")
                for m in res["direct"]:
                    print(f"    {m}")
                print(f"  transitively affected ({len(res['transitive'])}):")
                for m in res["transitive"]:
                    print(f"    {m}")
            return 0

        if args.cmd == "search":
            q = " ".join(args.query)
            rows = query.search(conn, q, args.limit)
            if as_json:
                _emit({"banner": fresh.banner(), "query": q, "results": rows}, True)
            else:
                print(fresh.banner())
                if not rows:
                    print(f"  no hits for {q!r}")
                for r in rows:
                    print(f"  {r['ref']}  [{r['kind']}] {r['name']}")
            return 0
    finally:
        conn.close()

    parser.error(f"unknown command {args.cmd!r}")  # unreachable (required subparser)
    return 2


if __name__ == "__main__":
    sys.exit(main())
