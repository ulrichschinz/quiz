"""Build the index by static analysis (Python ``ast``) — no execution.

Everything here is deterministic and stdlib-only. Edges that static analysis
cannot know (dynamic domain auto-discovery in ``app/main.py``, DI, reflection,
Jinja template -> route wiring) are deliberately NOT emitted — left empty, never
guessed (software-repo-prompt.md, pillar 8).
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from . import REPO_ROOT, SOURCE_ROOTS, TEMPLATE_ROOT
from .model import Endpoint, ImportEdge, IndexData, Symbol, Table, Template

_HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}


def iter_source_files(repo: Path = REPO_ROOT) -> list[Path]:
    """The Python files the index covers — shared with freshness fingerprinting."""
    out: list[Path] = []
    for root in SOURCE_ROOTS:
        base = repo / root
        if base.exists():
            out += [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]
    return sorted(out)


def iter_template_files(repo: Path = REPO_ROOT) -> list[Path]:
    base = repo / TEMPLATE_ROOT
    return sorted(base.rglob("*.html")) if base.exists() else []


def _dotted_module(path: Path, repo: Path) -> str:
    rel = path.relative_to(repo).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(module: str, is_pkg: bool, level: int, target: str | None) -> str:
    """Resolve ``from . import x`` style imports to an absolute dotted module."""
    parts = module.split(".")
    drop = (level - 1) if is_pkg else level
    base = parts[: len(parts) - drop] if drop <= len(parts) else []
    abs_parts = base + (target.split(".") if target else [])
    return ".".join(abs_parts)


def _short_doc(node: ast.AST) -> str:
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        doc = ast.get_docstring(node)
        if doc:
            return doc.strip().splitlines()[0].strip()
    return ""


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    sig = f"{node.name}({ast.unparse(node.args)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _class_signature(node: ast.ClassDef) -> str:
    bits = [ast.unparse(b) for b in node.bases]
    bits += [f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords]
    return f"({', '.join(bits)})" if bits else ""


def _is_table_class(node: ast.ClassDef) -> bool:
    return any(
        kw.arg == "table" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in node.keywords
    )


def _router_decorator(dec: ast.expr) -> tuple[str, str] | None:
    """Return (method, route) for an ``@router.<verb>(...)`` decorator, else None."""
    call = dec if isinstance(dec, ast.Call) else None
    attr = call.func if call else dec
    if not isinstance(attr, ast.Attribute) or attr.attr not in _HTTP_VERBS:
        return None
    obj = attr.value
    obj_ok = (isinstance(obj, ast.Name) and obj.id == "router") or (
        isinstance(obj, ast.Attribute) and obj.attr == "router"
    )
    if not obj_ok:
        return None
    route = ""
    if call and call.args and isinstance(call.args[0], ast.Constant):
        if isinstance(call.args[0].value, str):
            route = call.args[0].value
    return attr.attr, route


class _Extractor(ast.NodeVisitor):
    def __init__(self, module: str, path: str, data: IndexData) -> None:
        self.module = module
        self.path = path
        self.data = data
        self.stack: list[str] = []  # enclosing class qualnames

    def _qual(self, name: str) -> str:
        return ".".join(self.stack + [name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qual = self._qual(node.name)
        self.data.symbols.append(
            Symbol(
                name=node.name,
                qualname=qual,
                kind="class",
                module=self.module,
                path=self.path,
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                signature=_class_signature(node),
                doc=_short_doc(node),
                parent=".".join(self.stack),
            )
        )
        if _is_table_class(node):
            self.data.tables.append(
                Table(name=node.name, module=self.module, path=self.path, lineno=node.lineno)
            )
        self.stack.append(node.name)
        for child in node.body:  # one level into the class -> methods + nested classes
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)
        self.stack.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = "method" if self.stack else "function"
        self.data.symbols.append(
            Symbol(
                name=node.name,
                qualname=self._qual(node.name),
                kind=kind,
                module=self.module,
                path=self.path,
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                signature=_signature(node),
                doc=_short_doc(node),
                parent=".".join(self.stack),
            )
        )
        for dec in node.decorator_list:
            ep = _router_decorator(dec)
            if ep:
                method, route = ep
                self.data.endpoints.append(
                    Endpoint(
                        method=method,
                        route=route,
                        func=node.name,
                        module=self.module,
                        path=self.path,
                        lineno=node.lineno,
                    )
                )
        # Do not descend into function bodies: locals are not part of the surface.

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)


def _extract_imports(
    tree: ast.Module,
    module: str,
    is_pkg: bool,
    data: IndexData,
    candidates: list[tuple[str, str, int, str]],
) -> None:
    """Append definite import edges to ``data``; stash submodule guesses in
    ``candidates`` for a second pass that knows the full module set."""
    for node in tree.body:  # module-level imports only
        if isinstance(node, ast.Import):
            for alias in node.names:
                dst = alias.name
                data.imports.append(
                    ImportEdge(
                        module, dst, node.lineno, ast.unparse(node), not dst.startswith("app")
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            raw = ast.unparse(node)
            if node.level:
                base = _resolve_relative(module, is_pkg, node.level, node.module)
            else:
                base = node.module or ""
            base = base.strip(".")
            if node.module:
                # `from base import a, b`: edge to base; a/b *might* be submodules.
                if base:
                    data.imports.append(
                        ImportEdge(module, base, node.lineno, raw, not base.startswith("app"))
                    )
                for alias in node.names:
                    cand = f"{base}.{alias.name}".strip(".")
                    if cand:
                        candidates.append((module, cand, node.lineno, raw))
            else:
                # `from . import sub`: each name IS a submodule.
                for alias in node.names:
                    dst = f"{base}.{alias.name}".strip(".")
                    if dst:
                        data.imports.append(
                            ImportEdge(module, dst, node.lineno, raw, not dst.startswith("app"))
                        )


def _fingerprint(files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in files:
        st = p.stat()
        h.update(str(p).encode())
        h.update(str(st.st_size).encode())
        h.update(str(st.st_mtime_ns).encode())
    return h.hexdigest()


def build_index(repo: Path = REPO_ROOT) -> IndexData:
    data = IndexData()
    candidates: list[tuple[str, str, int, str]] = []
    py_files = iter_source_files(repo)
    for path in py_files:
        module = _dotted_module(path, repo)
        is_pkg = path.name == "__init__.py"
        rel = str(path.relative_to(repo))
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        data.symbols.append(
            Symbol(
                name=module.rsplit(".", 1)[-1],
                qualname=module,
                kind="module",
                module=module,
                path=rel,
                lineno=1,
                end_lineno=len(source.splitlines()) or 1,
                signature="",
                doc=_short_doc(tree),
                parent="",
            )
        )
        _Extractor(module, rel, data).visit(tree)
        _extract_imports(tree, module, is_pkg, data, candidates)

    # Second pass: promote `from pkg import name` guesses to edges only when
    # `pkg.name` is a real module in this repo (else it's just a name -> drop).
    known = {s.qualname for s in data.symbols if s.kind == "module"}
    seen = {(e.src, e.dst, e.lineno) for e in data.imports}
    for src, dst, lineno, raw in candidates:
        if dst in known and (src, dst, lineno) not in seen:
            data.imports.append(ImportEdge(src, dst, lineno, raw, False))
            seen.add((src, dst, lineno))

    for tpl in iter_template_files(repo):
        data.templates.append(Template(path=str(tpl.relative_to(repo))))

    data.fingerprint = _fingerprint(py_files + iter_template_files(repo))
    data.built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return data
