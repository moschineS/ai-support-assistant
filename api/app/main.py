"""Aventra Support Assist — FastAPI entry point.

Serves the JSON API under /api/* and, when a built UI exists in
app/static, the single-page agent workspace at /.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router

app = FastAPI(title="Aventra Support Assist", version="0.1.0")
app.include_router(router, prefix="/api")

_static = Path(__file__).parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")