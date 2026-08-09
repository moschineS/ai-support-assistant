"""Aventra Support Assist — FastAPI entry point.

Serves the JSON API under /api/* and, when a built UI exists in
app/static, the single-page agent workspace at /.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router

# On Windows, the stdlib mimetypes module consults the registry, which can
# map .js to text/plain — browsers then refuse the module script outright.
# Pin the types the SPA needs so serving works identically on every host.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")

app = FastAPI(title="Aventra Support Assist", version="0.1.0")
app.include_router(router, prefix="/api")

_static = Path(__file__).parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")