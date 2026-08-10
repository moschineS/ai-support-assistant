# ADR-004: Provider gateway — Ollama local / (Azure) OpenAI cloud, raw HTTP

**Status:** accepted · 2026-08-09

## Context

The solution must be *designed for cloud* yet *demonstrably runnable on a laptop*, and a
financial-services buyer will ask where the data goes. Chat and embeddings are the only two
model capabilities the system uses.

## Decision

A minimal gateway interface (`embed`, `chat_stream`) with two implementations selected by one
environment variable: **Ollama** (fully local, offline) and **OpenAI-compatible** (api.openai.com
locally, Azure OpenAI in the target — same wire format). Implemented with raw `httpx`, no LLM
framework and no provider SDK.

## Rationale

- **The sovereignty answer is executable.** "If your policy forbids external model calls, we flip
  one variable and run in-environment" — and the demo actually does it.
- **Two wire formats, ~200 lines.** LangChain-class frameworks buy abstraction we don't need at
  the price of dependency surface, opaque prompt assembly, and harder failure analysis. In a
  regulated context, being able to show the exact bytes sent to the model is a feature.
- **Streaming-first.** Both providers stream; the SSE relay to the browser is a straight pipe, and
  token usage is captured from each provider's final frame.

## Consequences

- Provider differences (embedding dimension, usage reporting) are handled explicitly: the seed
  records `(provider, model, dim)` and the API refuses on mismatch (ADR-005).
- Adding a third substrate (e.g. an in-house vLLM endpoint) is one class implementing two methods.
- No framework-managed retries/fallbacks: timeouts and errors surface as typed refusal events —
  which the fail-closed design wants anyway.