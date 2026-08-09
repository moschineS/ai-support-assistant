"""HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import db
from .config import get_settings
from .gateway import GatewayError
from .retrieval import RetrievalError, retrieve

router = APIRouter()


@router.get("/search")
def search(
    q: str = Query(..., min_length=2, max_length=2000),
    k: int = Query(default=None, ge=1, le=20),
) -> dict:
    s = get_settings()
    try:
        result = retrieve(q, k=k)
    except RetrievalError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except GatewayError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "query": result.query,
        "hits": result.hits,
        "best_similarity": round(result.best_similarity, 4),
        "keyword_hit": result.keyword_hit,
        "weak_evidence": result.is_weak(s.grounding_min_similarity),
    }


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