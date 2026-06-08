"""Plain dataclasses — the shape of what the index stores.

Deliberately dumb records: extraction (build.py), persistence (store.py) and
querying (query.py) all speak these, so the schema lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Symbol:
    """A module, class, function or method found in the AST."""

    name: str  # bare name, e.g. "score_submission"
    qualname: str  # dotted within the module, e.g. "ScoreEngine.run"
    kind: str  # module | class | function | method
    module: str  # dotted module path, e.g. "app.domains.quizzes.service"
    path: str  # repo-relative file, e.g. "app/domains/quizzes/service.py"
    lineno: int
    end_lineno: int
    signature: str  # "" for modules/classes-without-call-shape
    doc: str  # first line of the docstring, or ""
    parent: str  # enclosing class qualname, or ""


@dataclass(frozen=True)
class ImportEdge:
    """A module-level import edge: ``src`` imports ``dst``."""

    src: str  # dotted importer module
    dst: str  # dotted imported module (best-effort absolute)
    lineno: int
    raw: str  # the source line, e.g. "from app.core.db import get_session"
    external: bool  # True if dst is not part of our own app.* tree


@dataclass(frozen=True)
class Endpoint:
    """An HTTP route declared via ``@router.<method>(...)``."""

    method: str  # get | post | put | patch | delete
    route: str  # literal path arg if present, else "" (prefix is dynamic)
    func: str  # decorated function name
    module: str
    path: str
    lineno: int


@dataclass(frozen=True)
class Table:
    """A SQLModel table class (``table=True``)."""

    name: str
    module: str
    path: str
    lineno: int


@dataclass(frozen=True)
class Template:
    """A Jinja2 template file under ``templates/``."""

    path: str


@dataclass
class IndexData:
    """Everything one build produces, before it is written to the store."""

    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportEdge] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    templates: list[Template] = field(default_factory=list)
    fingerprint: str = ""
    built_at: str = ""
