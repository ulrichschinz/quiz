"""interfaces.web — Jinja2 UI routers.

`register(app)` wires the web delivery layer:

1. Auto-discovery: iterate `app.domains.*` and include any `router` a domain
   exposes (a freshly scaffolded domain lands handlers in
   `app/domains/X/router.py`; picked up with zero central-registry edits).
2. The interface-shaped routers (public site, auth, admin) — these are
   delivery-shaped, not domain-shaped, so they live here.
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import FastAPI

from app import domains as _domains_pkg
from app.interfaces.web import admin, auth, public

_WEB_ROUTERS = (public, auth, admin)


def _discover_domain_routers(app: FastAPI) -> None:
    """Include `router` from every `app.domains.<x>.router` that exists."""
    for mod in pkgutil.iter_modules(_domains_pkg.__path__):
        try:
            router_mod = importlib.import_module(f"app.domains.{mod.name}.router")
        except ModuleNotFoundError:
            continue
        router = getattr(router_mod, "router", None)
        if router is not None:
            app.include_router(router)


def register(app: FastAPI) -> None:
    _discover_domain_routers(app)
    for module in _WEB_ROUTERS:
        app.include_router(module.router)
