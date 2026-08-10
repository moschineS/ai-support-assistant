# ADR-003: Hybrid retrieval fused with Reciprocal Rank Fusion

**Status:** accepted · 2026-08-09

## Context

Support queries split into two shapes: paraphrase ("I'm not getting the approval thing on my
phone") and exact tokens ("error EB-1042", "AventraGiro Plus"). Embeddings handle the first and
are mediocre at the second — error codes are near-random strings in embedding space. Keyword
search is the mirror image.

## Decision

Every query runs both retrievals — embedding cosine and full-text (`tsvector` / FTS5) — and the
two ranked lists are fused with **Reciprocal Rank Fusion**: `score(d) = Σ 1/(K + rank_d)`, K=60,
implemented once in shared code above both storage backends.

## Rationale

- **RRF consumes ranks, not scores.** Cosine similarity and BM25/ts_rank live on incomparable
  scales; any weighted score blend needs per-corpus tuning and re-tuning as the corpus drifts.
  RRF has one insensitive parameter and is the standard baseline fusion in IR literature.
- **Agreement wins.** A chunk found by both legs outranks a chunk found by one — exactly the
  behaviour a support corpus wants (the EB-1042 incident is both semantically *and* lexically
  right for "code EB-1042 not arriving").
- **Explainable.** Each source in the UI shows its semantic similarity and keyword rank — an
  auditor or a sceptical agent can see *why* a source surfaced.

## Consequences

- The deterministic evidence gate keys on the strongest signal (best cosine, keyword presence)
  rather than the fused score, since RRF scores have no absolute meaning.
- A cross-encoder reranker can slot in after fusion later without touching either retrieval leg.