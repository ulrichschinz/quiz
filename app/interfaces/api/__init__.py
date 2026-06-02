"""interfaces.api — public JSON API. `register(app)` mounts the router."""

from __future__ import annotations

from fastapi import FastAPI

from app.interfaces.api.router import router


def register(app: FastAPI) -> None:
    app.include_router(router)
