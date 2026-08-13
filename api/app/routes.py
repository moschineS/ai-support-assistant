"""HTTP routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import db
from .assist import assist_events
from .config import get_settings
from .gateway import GatewayError
from .retrieval import RetrievalError, retrieve

router = APIRouter()


class AssistRequest(BaseModel):
    message: str = Field(min_length=2, max_length=8000)
    k: int | None = Field(default=None, ge=1, le=20)


@router.post("/assist")
def assist(req: AssistRequest) -> StreamingResponse:
    """Stream a grounded draft as Server-Sent Events.

    Event contract (see assist.py): meta -> token* -> done | refusal | error.
    """

    def stream():
        try:
            for event, payload in assist_events(req.message, k=req.k):
                yield f"event: {event}\ndata: {json.dumps(payload)}\n\n"
        except Exception as e:  # last-resort: report instead of dropping the SSE
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/audit")
def audit(limit: int = Query(default=20, ge=1, le=200)) -> dict:
    try:
        return {"entries": db.get_store().audit_recent(limit)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


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
            "provider": "openai",
            "seeded": embedding_meta is not None,
            "embedding": embedding_meta,
            **n,
        }
    except Exception as e:  # health must never 500 — report, don't raise
        return {
            "status": "degraded",
            "db": "down",
            "provider": "openai",
            "seeded": False,
            "error": str(e),
        }