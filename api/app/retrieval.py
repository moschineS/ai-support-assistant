"""Hybrid retrieval: vector + keyword candidates, fused with Reciprocal Rank Fusion.

Both storage backends return plain ranked lists; everything that decides
the final ranking lives here, in one shared code path, so the backends
cannot drift in semantics.

RRF instead of score blending: cosine similarities and BM25/ts_rank live
on incomparable scales, and any weighted sum of them needs per-corpus
tuning. RRF only consumes ranks — ``score(d) = sum 1/(K + rank)`` — and
is the standard, defensible fusion for exactly this situation (ADR-003).

Fail-closed guards (ADR-005):
- unseeded store -> refuse with instructions, never empty-answer
- seeded embedding model != active embedding model -> refuse (querying a
  vector space with a different model's embeddings must be a hard error,
  not a silently wrong ranking)
- weak evidence (best cosine below threshold, no keyword hit) is
  reported to the caller; the assist layer refuses to draft from it
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Settings, get_settings
from .db import Store, get_store
from .gateway import Gateway, get_gateway

RRF_K = 60
CANDIDATE_FACTOR = 3  # each ranked list is fetched k * factor deep


class RetrievalError(RuntimeError):
    """Deterministic refusal with a user-safe reason."""


@dataclass
class RetrievalResult:
    query: str
    hits: list[dict[str, Any]] = field(default_factory=list)
    best_similarity: float = 0.0
    keyword_hit: bool = False

    def is_weak(self, min_similarity: float) -> bool:
        return not self.hits or (
            self.best_similarity < min_similarity and not self.keyword_hit
        )


def check_seed_compatible(store: Store, s: Settings) -> dict[str, Any]:
    """The seeded embedding space must match the active embedding model."""
    meta = store.get_meta("embedding")
    if meta is None:
        raise RetrievalError(
            "knowledge base is not seeded — run: python -m app.ingest"
        )
    if meta.get("model") != s.openai_embed_model:
        raise RetrievalError(
            f"knowledge base was seeded with embedding model"
            f" '{meta.get('model')}' but OPENAI_EMBED_MODEL="
            f"{s.openai_embed_model} is active — re-run: python -m app.ingest"
        )
    return meta


def rrf_fuse(ranked_lists: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def retrieve(
    query: str,
    *,
    store: Store | None = None,
    gateway: Gateway | None = None,
    s: Settings | None = None,
    k: int | None = None,
) -> RetrievalResult:
    s = s or get_settings()
    store = store or get_store()
    gateway = gateway or get_gateway(s)
    k = k or s.retrieval_k

    check_seed_compatible(store, s)

    qvec = gateway.embed([query])[0]
    depth = k * CANDIDATE_FACTOR
    vec_ranked = store.vector_ranked(qvec, depth)
    kw_ranked = store.keyword_ranked(query, depth)

    fused = rrf_fuse([[c for c, _ in vec_ranked], [c for c, _ in kw_ranked]])
    top_ids = sorted(fused, key=fused.__getitem__, reverse=True)[:k]

    vec_sim = dict(vec_ranked)
    kw_rank = {cid: i + 1 for i, (cid, _) in enumerate(kw_ranked)}
    hits = []
    for chunk in store.fetch(top_ids):
        cid = chunk["id"]
        hits.append(
            {
                **chunk,
                "rrf_score": round(fused[cid], 5),
                "vector_similarity": (
                    round(vec_sim[cid], 4) if cid in vec_sim else None
                ),
                "keyword_rank": kw_rank.get(cid),
            }
        )

    return RetrievalResult(
        query=query,
        hits=hits,
        best_similarity=vec_ranked[0][1] if vec_ranked else 0.0,
        keyword_hit=bool(kw_ranked),
    )