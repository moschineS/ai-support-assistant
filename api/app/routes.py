"""HTTP routes. Phase 2: health; search/assist/audit follow."""

from __future__ import annotations

from fastapi import APIRouter

from . import db
from .config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    try:
        store = db.get_store()
        embedding_meta = store.get_meta("embedding")
        n = store.counts()
        return {
            "status": "ok",
            "db": "up",
            "backend": store.backend,
            "provider": s.provider,
            "seeded": embedding_meta is not None,
            "embedding": embedding_meta,
            **n,
        }
    except Exception as e:  # health must never 500 — report, don't raise
        return {
            "status": "degraded",
            "db": "down",
            "provider": s.provider,
            "seeded": False,
            "error": str(e),
        }