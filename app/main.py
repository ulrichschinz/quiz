"""app.main — FastAPI application assembly.

`load_dotenv()` runs before the engine-bearing modules construct anything from
settings at import time (db.py reads DATABASE_URL at module load), so the
imports below are deliberately ordered after it — hence the file-scoped E402
ignore in pyproject.toml.

The delivery layer is wired through `app.interfaces.{web,api}`: `web.register`
includes the Jinja routers (+ domain auto-discovery), `api.register` mounts the
JSON router. `NeedsLoginException` (raised by `require_admin`) maps to a login
redirect.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import create_db  # noqa: E402
from app.core.errors import NeedsLoginException  # noqa: E402
from app.interfaces import api as api_iface  # noqa: E402
from app.interfaces import web as web_iface  # noqa: E402

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_db()
    yield


app = FastAPI(title="Agentic Reach Quiz", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(NeedsLoginException)
async def needs_login_handler(request: Request, exc: NeedsLoginException) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


web_iface.register(app)
api_iface.register(app)
