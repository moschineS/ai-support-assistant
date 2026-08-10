# ADR-005: Fail-closed grounding, mandatory citations, audit log

**Status:** accepted · 2026-08-09

## Context

The one unacceptable failure mode for a bank's support tooling is a fluent, wrong answer — a fee,
deadline, or security instruction the knowledge base never said. LLM output quality cannot be
guaranteed; system behaviour around the LLM can.

## Decision

Every step that can go wrong resolves to an explicit **refusal**, never a best-effort answer:

1. Unseeded store or embedding-provider mismatch → refuse before retrieval (a 768-dim query
   against 1536-dim vectors must be a hard error, not a silently wrong ranking).
2. Weak evidence (best cosine below threshold, no keyword hit) → refuse **without calling the
   LLM**. The model never sees a question the corpus cannot support.
3. The model may declare insufficiency (`COVERAGE_GAP` sentinel) → refusal, by design not failure.
4. Post-validation: a draft with **no citations**, or citing sources that were not provided, is
   discarded and surfaced as a refusal — the discarded draft is kept in the audit row.
5. Every request writes exactly one audit row: query, retrieved chunk ids + scores, draft or
   refusal reason, provider, model, latency, token usage.

## Rationale

- Deterministic guards are auditable in minutes; prompt-only guardrails are not. The prompt asks
  for grounded behaviour, but the *system* enforces the consequences.
- Defense in depth demonstrably works: in live testing, an out-of-corpus request slipped past the
  similarity gate (banking-adjacent wording), the model wrote an uncitable reply — and the
  citation validator caught it. Layer 4 exists for exactly the cases layer 2 misses.
- The audit row is the compliance product: who asked what, what evidence was used, what was
  drafted or refused and why, at what cost.

## Consequences

- Some answerable-by-a-human requests get refused (false negatives). Accepted: in this domain a
  refusal costs seconds, a confident fabrication costs trust — thresholds are tunable per corpus.
- Citation validation constrains the model's output format; the smallest models occasionally fail
  it and their drafts are discarded. That cost is visible in the eval's draft-rate metric instead
  of hidden in output quality.