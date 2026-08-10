# ADR-002: pgvector in Postgres over a dedicated vector database

**Status:** accepted · 2026-08-09

## Context

The corpus is a mid-sized company's support knowledge: thousands to low tens of thousands of
chunks, updated occasionally. Retrieval needs vector similarity *and* keyword search *and* an
audit log.

## Decision

Vectors live in Postgres via the `pgvector` extension, next to the chunk metadata, the full-text
index (`tsvector`), and the audit log. No dedicated vector database.

## Rationale

- **One moving part.** One backup/restore story, one connection pool, one transactional boundary —
  a chunk, its vector, and its keyword index cannot drift apart.
- **Data residency & vendor scope.** In a financial institution every new data-bearing vendor is a
  DORA/outsourcing conversation. Postgres is already on every bank's approved list; a vector-DB
  SaaS holding customer-adjacent text is a new third-party dependency for no capability we need.
- **Scale honesty.** Exact scan over a few thousand vectors is single-digit milliseconds. The
  first real scaling step is an `hnsw` index *inside* pgvector; a dedicated engine becomes
  interesting at the hundreds-of-millions-of-vectors mark, which a support corpus will not reach.
- **The keyword leg is native.** Hybrid search (ADR-003) needs full-text ranking anyway — Postgres
  ships it; a vector DB would need a second engine or a bolt-on.

## Consequences

- The demo also ships a SQLite backend (FTS5 + in-process cosine) behind the same store
  interface — proof the storage choice is an adapter, not an architecture.
- Embedding dimension is fixed per seed; switching embedding models rebuilds the table (documented,
  ~2 minutes at demo scale; a blue/green re-index at production scale).