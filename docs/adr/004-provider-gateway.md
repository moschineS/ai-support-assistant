# ADR-004: Model gateway — OpenAI API locally, Azure OpenAI in the cloud, raw HTTP

**Status:** accepted · 2026-08-09 (revised 2026-08-14: single substrate)

## Context

The solution must be *designed for cloud* yet *demonstrably runnable on a laptop*, and a
financial-services buyer will ask where the data goes. Chat and embeddings are the only two
model capabilities the system uses.

## Decision

A minimal gateway (`embed`, `chat_stream`) implemented with raw `httpx` against the
OpenAI-compatible wire format — **api.openai.com locally, Azure OpenAI in the target
architecture**. Same format, so the move to the cloud target is an endpoint and credential
change, not a code change. No LLM framework, no provider SDK.

## Rationale

- **One wire format, ~120 lines.** LangChain-class frameworks buy abstraction this problem does
  not need, at the price of dependency surface, opaque prompt assembly, and harder failure
  analysis. In a regulated context, being able to show the exact bytes sent to the model is a
  feature.
- **Streaming-first.** The SSE relay to the browser is a straight pipe, and token usage is
  captured from the stream's final frame.
- **Typed failures.** Every transport or HTTP error is wrapped in `GatewayError`, so the assist
  pipeline converts infrastructure failures into audited refusals instead of leaking raw
  exceptions (ADR-005).
- **The interface is the sovereignty answer.** The gateway is deliberately just two methods: a
  client with a strict no-egress policy gets an in-environment model server behind the same
  interface — one new class, zero caller changes. The storage layer's dual backend
  (pgvector/SQLite, ADR-002) demonstrates exactly this adapter pattern already.

## Consequences

- The seed records the embedding model and dimension; the API refuses to serve when the running
  embedding model disagrees with the seeded one — embeddings from different models are
  incompatible vector spaces (enforced in `retrieval.check_seed_compatible`).
- Live drafting requires reachability of the model endpoint; the demo script treats network
  availability as a rehearsal item and defines evidence-based fallbacks.
- No framework-managed retries: timeouts and errors surface as typed refusal events, which the
  fail-closed design wants anyway.