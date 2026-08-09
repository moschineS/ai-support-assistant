"""Postgres access layer: connection pool + schema DDL.

The schema is created by the seed CLI (``python -m app.ingest``), not at
API startup. An unseeded database is a refusal condition the API reports
honestly, never something it silently repairs (fail-closed; ADR-005).

The ``chunks`` table is created dynamically because the embedding
dimension depends on the active provider (nomic-embed-text = 768,
text-embedding-3-small = 1536). The seed records the active
``(provider, model, dim)`` in ``meta`` and the API refuses to serve
if the running provider disagrees with the seeded one.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url, min_size=1, max_size=5, open=True
        )
    return _pool


DDL_STATIC = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS meta (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id                bigserial PRIMARY KEY,
    ts                timestamptz NOT NULL DEFAULT now(),
    request_text      text NOT NULL,
    retrieved         jsonb NOT NULL,
    draft             text,
    refused           boolean NOT NULL DEFAULT false,
    refusal_reason    text,
    provider          text NOT NULL,
    chat_model        text NOT NULL,
    latency_ms        integer,
    prompt_tokens     integer,
    completion_tokens integer
);
"""


def chunks_ddl(dim: int) -> str:
    # Exact nearest-neighbour scan is intentional at this corpus size
    # (hundreds of chunks); an ivfflat/hnsw index would be added at the
    # scale where recall/latency demands it (see ADR-002).
    return f"""
DROP TABLE IF EXISTS chunks;
CREATE TABLE chunks (
    id          text PRIMARY KEY,
    doc_id      text NOT NULL,
    doc_title   text NOT NULL,
    source_type text NOT NULL,
    product     text,
    doc_date    date,
    chunk_index integer NOT NULL,
    content     text NOT NULL,
    embedding   vector({dim}) NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX chunks_tsv_idx ON chunks USING gin(tsv);
CREATE INDEX chunks_doc_idx ON chunks (doc_id);
"""


def set_meta(conn: psycopg.Connection, key: str, value: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, json.dumps(value)),
    )


def get_meta(key: str) -> dict[str, Any] | None:
    """Return the meta value, or None when unset or the schema is absent."""
    try:
        with get_pool().connection() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = %s", (key,)
            ).fetchone()
            return row[0] if row else None
    except psycopg.errors.UndefinedTable:
        return None


def counts() -> dict[str, int]:
    try:
        with get_pool().connection() as conn:
            chunks, docs = conn.execute(
                "SELECT count(*), count(DISTINCT doc_id) FROM chunks"
            ).fetchone()
            return {"chunks": chunks, "docs": docs}
    except psycopg.errors.UndefinedTable:
        return {"chunks": 0, "docs": 0}