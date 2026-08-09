"""Grounded draft generation — fail-closed at every step (ADR-005).

The pipeline for one assist request:

1. Hybrid retrieval (may refuse: unseeded store, provider mismatch).
2. Deterministic evidence gate: weak evidence -> refusal WITHOUT calling
   the LLM. The model never sees a question the corpus cannot answer.
3. Streamed draft generation from the numbered sources only.
4. Deterministic post-validation: the draft must cite at least one
   provided source, must not cite sources that were not provided, and a
   model-reported coverage gap is converted into a refusal.
5. Audit: every request writes exactly one audit row — drafted or
   refused, with the reason.

The function yields ``(event, payload)`` tuples that the route layer
serializes as Server-Sent Events:

    meta    {sources, weak}          first, so the UI shows evidence early
    token   {t}                      draft text increments
    done    {audit_id, draft, citations, usage, latency_ms}
    refusal {reason, detail, audit_id?}
    error   {detail}                 infrastructure failure mid-stream
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from typing import Any

from .config import Settings, get_settings
from .db import Store, get_store
from .gateway import Gateway, GatewayError, get_gateway
from .retrieval import RetrievalError, retrieve

log = logging.getLogger("assist")

COVERAGE_GAP_TOKEN = "COVERAGE_GAP"
CITATION_RE = re.compile(r"\[S(\d+)\]")

SYSTEM_PROMPT = f"""You are the drafting assistant for customer support agents at Bank Aventra, a retail bank.
Write a reply that the AGENT can send to the CUSTOMER, based ONLY on the numbered sources provided.

Rules:
- Use only facts from the sources. Never invent policies, fees, deadlines, error codes, or steps.
- After every factual claim, cite the source label in square brackets, e.g. [S1]. Every paragraph must contain at least one citation.
- If the sources do not cover the customer's request, output exactly: {COVERAGE_GAP_TOKEN}
  Never write an apology reply saying the information is unavailable — the bare token is the correct output in that case.
- Sources of type "procedure" are internal instructions for agents: let them guide what you write, but never quote internal wording (e.g. deadlines for agents, escalation rules) to the customer.
- Tone: professional, warm, concise. Address the customer directly, start with a short acknowledgement of their concern, end with one clear next step. Sign as "Your Aventra support team".
"""


def _source_label(i: int) -> str:
    return f"S{i + 1}"


def _sources_payload(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": _source_label(i),
            "id": h["id"],
            "doc_id": h["doc_id"],
            "doc_title": h["doc_title"],
            "source_type": h["source_type"],
            "product": h.get("product"),
            "doc_date": h.get("doc_date"),
            "content": h["content"],
            "rrf_score": h["rrf_score"],
            "vector_similarity": h.get("vector_similarity"),
            "keyword_rank": h.get("keyword_rank"),
        }
        for i, h in enumerate(hits)
    ]


def _context_block(sources: list[dict[str, Any]]) -> str:
    parts = []
    for src in sources:
        head = (
            f"{src['label']} ({src['source_type']}"
            + (f", {src['doc_date']}" if src["doc_date"] else "")
            + f"): {src['doc_title']}"
        )
        parts.append(f"{head}\n{src['content']}")
    return "\n\n---\n\n".join(parts)


def _audit(
    store: Store,
    *,
    message: str,
    sources: list[dict[str, Any]],
    provider: str,
    chat_model: str,
    t0: float,
    draft: str | None = None,
    refused: bool = False,
    refusal_reason: str | None = None,
    usage: tuple[int | None, int | None] = (None, None),
) -> int | None:
    try:
        return store.audit_insert(
            {
                "request_text": message,
                "retrieved": [
                    {
                        "label": s["label"],
                        "id": s["id"],
                        "rrf_score": s["rrf_score"],
                        "vector_similarity": s["vector_similarity"],
                        "keyword_rank": s["keyword_rank"],
                    }
                    for s in sources
                ],
                "draft": draft,
                "refused": refused,
                "refusal_reason": refusal_reason,
                "provider": provider,
                "chat_model": chat_model,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "prompt_tokens": usage[0],
                "completion_tokens": usage[1],
            }
        )
    except Exception:
        log.exception("audit write failed")
        return None


def assist_events(
    message: str,
    *,
    store: Store | None = None,
    gateway: Gateway | None = None,
    s: Settings | None = None,
    k: int | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    s = s or get_settings()
    store = store or get_store()
    gateway = gateway or get_gateway(s)
    chat_model = s.ollama_chat_model if s.provider == "ollama" else s.openai_chat_model
    t0 = time.perf_counter()

    def refuse(reason: str, detail: str, sources: list[dict[str, Any]], **audit_kw):
        audit_id = _audit(
            store, message=message, sources=sources, provider=s.provider,
            chat_model=chat_model, t0=t0, refused=True, refusal_reason=reason,
            **audit_kw,
        )
        return "refusal", {"reason": reason, "detail": detail, "audit_id": audit_id}

    # 1. Retrieval -----------------------------------------------------
    try:
        result = retrieve(message, store=store, gateway=gateway, s=s, k=k)
    except RetrievalError as e:
        yield refuse("retrieval_unavailable", str(e), [])
        return
    except GatewayError as e:
        yield refuse("gateway_unavailable", str(e), [])
        return

    sources = _sources_payload(result.hits)

    # 2. Deterministic evidence gate — the LLM is never asked to answer
    #    a question the corpus cannot support.
    if result.is_weak(s.grounding_min_similarity):
        yield "meta", {"sources": sources, "weak": True}
        yield refuse(
            "weak_evidence",
            "The knowledge base has no sufficiently relevant source for this"
            " request. No draft was generated — handle manually or rephrase.",
            sources,
        )
        return

    yield "meta", {"sources": sources, "weak": False}

    # 3. Streamed generation ------------------------------------------
    user_prompt = (
        f"Customer message:\n{message}\n\nSources:\n{_context_block(sources)}"
    )
    pieces: list[str] = []
    try:
        for piece in gateway.chat_stream(SYSTEM_PROMPT, user_prompt):
            pieces.append(piece)
            yield "token", {"t": piece}
    except GatewayError as e:
        yield refuse("gateway_error", str(e), sources)
        return
    except Exception as e:  # network drop mid-stream etc.
        log.exception("chat stream failed")
        yield refuse("gateway_error", f"generation failed: {e}", sources)
        return

    draft = "".join(pieces).strip()
    usage = getattr(gateway, "last_usage", (None, None))

    # 4. Deterministic post-validation --------------------------------
    if COVERAGE_GAP_TOKEN in draft:
        yield refuse(
            "model_reported_gap",
            "The model judged the retrieved sources insufficient for this"
            " request. No draft was produced.",
            sources, usage=usage,
        )
        return

    cited = {int(m) for m in CITATION_RE.findall(draft)}
    valid = set(range(1, len(sources) + 1))
    if not cited:
        yield refuse(
            "draft_missing_citations",
            "The draft contained no source citations and was discarded"
            " (citations are mandatory).",
            sources, draft=draft, usage=usage,
        )
        return
    if not cited <= valid:
        bad = ", ".join(f"S{i}" for i in sorted(cited - valid))
        yield refuse(
            "draft_citation_invalid",
            f"The draft cited non-existent sources ({bad}) and was discarded.",
            sources, draft=draft, usage=usage,
        )
        return

    # 5. Audit + done --------------------------------------------------
    audit_id = _audit(
        store, message=message, sources=sources, provider=s.provider,
        chat_model=chat_model, t0=t0, draft=draft, usage=usage,
    )
    yield "done", {
        "audit_id": audit_id,
        "draft": draft,
        "citations": sorted(_source_label(i - 1) for i in cited),
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }