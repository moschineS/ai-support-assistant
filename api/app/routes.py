"""HTTP routes. Phase 1: health only; search/assist/audit follow."""

from __future__ import annotations

import psycopg
from fastapi import APIRouter

from . import db
from .config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    try:
        embedding_meta = db.get_meta("embedding")
        n = db.counts()
        db_status = "up"
    except psycopg.OperationalError:
        embedding_meta, n, db_status = None, {"chunks": 0, "docs": 0}, "down"

    return {
        "status": "ok" if db_status == "up" else "degraded",
        "db": db_status,
        "provider": s.provider,
        "seeded": embedding_meta is not None,
        "embedding": embedding_meta,
        **n,
    }