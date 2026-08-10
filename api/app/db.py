"""Storage layer: one interface, two backends, chosen by DATABASE_URL.

- ``postgresql://...`` -> ``PgStore``: pgvector cosine + tsvector full-text.
  The production path (mirrors the cloud target: PG Flexible Server).
- ``sqlite:///...``    -> ``SqliteStore``: FTS5 keyword + pure-Python cosine.
  Zero-infrastructure fallback: the demo survives a machine without Docker,
  and tests run against a throwaway file.

Both backends expose identical ranked lists; hybrid fusion (RRF) happens
in ``retrieval.py`` in one shared code path, so the backends cannot drift
in ranking semantics.

The schema is created by the seed CLI (``python -m app.ingest``), not at
API startup. An unseeded database is a refusal condition the API reports
honestly, never something it silently repairs (fail-closed; ADR-005).
The ``chunks`` table is created per-seed because the embedding dimension
depends on the provider (nomic-embed-text = 768, text-embedding-3-small
= 1536); the seed records ``(provider, model, dim)`` in ``meta`` and the
API refuses to serve when the running provider disagrees.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from array import array
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import REPO_ROOT, get_settings


def _iso(d: Any) -> str | None:
    if d is None:
        return None
    if isinstance(d, (dt.date, dt.datetime)):
        return d.isoformat()
    return str(d)


# ---------------------------------------------------------------- Postgres

class PgStore:
    backend = "postgres"

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

    def __init__(self, url: str):
        from psycopg_pool import ConnectionPool

        # timeout=5: a dead database must surface as a fast, explicit error
        # (health shows "degraded"), not a 30s hang per request.
        self._pool = ConnectionPool(url, min_size=1, max_size=5, open=True, timeout=5)

    # -- schema / seed -------------------------------------------------

    def ensure_base(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(self.DDL_STATIC)

    def recreate_chunks(self, dim: int) -> None:
        # Exact nearest-neighbour scan is intentional at this corpus size
        # (hundreds of chunks); an hnsw index is the documented next step
        # at real scale (ADR-002).
        with self._pool.connection() as conn:
            conn.execute(
                f"""
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
                    tsv         tsvector GENERATED ALWAYS AS
                                (to_tsvector('english', content)) STORED
                );
                CREATE INDEX chunks_tsv_idx ON chunks USING gin(tsv);
                CREATE INDEX chunks_doc_idx ON chunks (doc_id);
                """
            )

    def insert_chunks(self, rows: list[dict[str, Any]]) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (id, doc_id, doc_title, source_type,"
                " product, doc_date, chunk_index, content, embedding)"
                " VALUES (%(id)s, %(doc_id)s, %(doc_title)s, %(source_type)s,"
                " %(product)s, %(doc_date)s, %(chunk_index)s, %(content)s,"
                " %(embedding_literal)s::vector)",
                rows,
            )

    # -- meta / counts -------------------------------------------------

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (%s, %s)"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, json.dumps(value)),
            )

    def get_meta(self, key: str) -> dict[str, Any] | None:
        import psycopg

        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = %s", (key,)
                ).fetchone()
                return row[0] if row else None
        except psycopg.errors.UndefinedTable:
            return None

    def counts(self) -> dict[str, int]:
        import psycopg

        try:
            with self._pool.connection() as conn:
                chunks, docs = conn.execute(
                    "SELECT count(*), count(DISTINCT doc_id) FROM chunks"
                ).fetchone()
                return {"chunks": chunks, "docs": docs}
        except psycopg.errors.UndefinedTable:
            return {"chunks": 0, "docs": 0}

    # -- retrieval primitives -----------------------------------------

    def vector_ranked(self, qvec: list[float], k: int) -> list[tuple[str, float]]:
        lit = "[" + ",".join(f"{x:.7g}" for x in qvec) + "]"
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, 1 - (embedding <=> %s::vector) AS sim"
                " FROM chunks ORDER BY embedding <=> %s::vector LIMIT %s",
                (lit, lit, k),
            ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def keyword_ranked(self, query: str, k: int) -> list[tuple[str, float]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, ts_rank(tsv, plainto_tsquery('english', %s)) AS r"
                " FROM chunks WHERE tsv @@ plainto_tsquery('english', %s)"
                " ORDER BY r DESC LIMIT %s",
                (query, query, k),
            ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def fetch(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, doc_id, doc_title, source_type, product,"
                " doc_date, chunk_index, content FROM chunks WHERE id = ANY(%s)",
                (ids,),
            ).fetchall()
        by_id = {
            r[0]: {
                "id": r[0], "doc_id": r[1], "doc_title": r[2],
                "source_type": r[3], "product": r[4], "doc_date": _iso(r[5]),
                "chunk_index": r[6], "content": r[7],
            }
            for r in rows
        }
        return [by_id[i] for i in ids if i in by_id]

    # -- audit ---------------------------------------------------------

    def audit_insert(self, e: dict[str, Any]) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO audit_log (request_text, retrieved, draft, refused,"
                " refusal_reason, provider, chat_model, latency_ms,"
                " prompt_tokens, completion_tokens)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    e["request_text"], json.dumps(e["retrieved"]), e.get("draft"),
                    e.get("refused", False), e.get("refusal_reason"),
                    e["provider"], e["chat_model"], e.get("latency_ms"),
                    e.get("prompt_tokens"), e.get("completion_tokens"),
                ),
            ).fetchone()
            return int(row[0])

    def audit_recent(self, limit: int) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, ts, request_text, retrieved, draft, refused,"
                " refusal_reason, provider, chat_model, latency_ms,"
                " prompt_tokens, completion_tokens"
                " FROM audit_log ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0], "ts": _iso(r[1]), "request_text": r[2],
                "retrieved": r[3], "draft": r[4], "refused": r[5],
                "refusal_reason": r[6], "provider": r[7], "chat_model": r[8],
                "latency_ms": r[9], "prompt_tokens": r[10],
                "completion_tokens": r[11],
            }
            for r in rows
        ]


# ----------------------------------------------------------------- SQLite

class SqliteStore:
    backend = "sqlite"

    def __init__(self, path: Path):
        self._path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- schema / seed -------------------------------------------------

    def ensure_base(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    request_text TEXT NOT NULL,
                    retrieved TEXT NOT NULL,
                    draft TEXT,
                    refused INTEGER NOT NULL DEFAULT 0,
                    refusal_reason TEXT,
                    provider TEXT NOT NULL,
                    chat_model TEXT NOT NULL,
                    latency_ms INTEGER,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER
                );
                """
            )

    def recreate_chunks(self, dim: int) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                DROP TABLE IF EXISTS chunks;
                DROP TABLE IF EXISTS chunks_fts;
                CREATE TABLE chunks (
                    id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    doc_title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    product TEXT,
                    doc_date TEXT,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL
                );
                CREATE VIRTUAL TABLE chunks_fts USING fts5(
                    content, id UNINDEXED
                );
                """
            )

    def insert_chunks(self, rows: list[dict[str, Any]]) -> None:
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO chunks (id, doc_id, doc_title, source_type,"
                " product, doc_date, chunk_index, content, embedding)"
                " VALUES (:id, :doc_id, :doc_title, :source_type, :product,"
                " :doc_date, :chunk_index, :content, :embedding_blob)",
                rows,
            )
            conn.executemany(
                "INSERT INTO chunks_fts (content, id) VALUES (:content, :id)",
                rows,
            )

    # -- meta / counts -------------------------------------------------

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    def get_meta(self, key: str) -> dict[str, Any] | None:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = ?", (key,)
                ).fetchone()
                return json.loads(row[0]) if row else None
        except sqlite3.OperationalError:
            return None

    def counts(self) -> dict[str, int]:
        try:
            with self._conn() as conn:
                chunks, docs = conn.execute(
                    "SELECT count(*), count(DISTINCT doc_id) FROM chunks"
                ).fetchone()
                return {"chunks": chunks, "docs": docs}
        except sqlite3.OperationalError:
            return {"chunks": 0, "docs": 0}

    # -- retrieval primitives -----------------------------------------

    def vector_ranked(self, qvec: list[float], k: int) -> list[tuple[str, float]]:
        q = array("f", qvec)
        qnorm = math.sqrt(sum(x * x for x in q)) or 1.0
        scored: list[tuple[str, float]] = []
        with self._conn() as conn:
            for cid, blob in conn.execute("SELECT id, embedding FROM chunks"):
                v = array("f")
                v.frombytes(blob)
                dot = sum(a * b for a, b in zip(q, v))
                vnorm = math.sqrt(sum(x * x for x in v)) or 1.0
                scored.append((cid, dot / (qnorm * vnorm)))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    def keyword_ranked(self, query: str, k: int) -> list[tuple[str, float]]:
        # Quote each term so FTS5 operators in user text cannot inject syntax.
        terms = [t for t in "".join(
            c if c.isalnum() or c in "-_" else " " for c in query
        ).split() if t]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, bm25(chunks_fts) FROM chunks_fts"
                " WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
                (match, k),
            ).fetchall()
        # bm25() is ascending-better; negate so higher = better like ts_rank.
        return [(r[0], -float(r[1])) for r in rows]

    def fetch(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, doc_id, doc_title, source_type, product,"
                f" doc_date, chunk_index, content FROM chunks"
                f" WHERE id IN ({marks})",
                ids,
            ).fetchall()
        by_id = {
            r[0]: {
                "id": r[0], "doc_id": r[1], "doc_title": r[2],
                "source_type": r[3], "product": r[4], "doc_date": r[5],
                "chunk_index": r[6], "content": r[7],
            }
            for r in rows
        }
        return [by_id[i] for i in ids if i in by_id]

    # -- audit ---------------------------------------------------------

    def audit_insert(self, e: dict[str, Any]) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO audit_log (request_text, retrieved, draft, refused,"
                " refusal_reason, provider, chat_model, latency_ms,"
                " prompt_tokens, completion_tokens)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    e["request_text"], json.dumps(e["retrieved"]), e.get("draft"),
                    int(e.get("refused", False)), e.get("refusal_reason"),
                    e["provider"], e["chat_model"], e.get("latency_ms"),
                    e.get("prompt_tokens"), e.get("completion_tokens"),
                ),
            )
            return int(cur.lastrowid)

    def audit_recent(self, limit: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, ts, request_text, retrieved, draft, refused,"
                " refusal_reason, provider, chat_model, latency_ms,"
                " prompt_tokens, completion_tokens"
                " FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0], "ts": r[1], "request_text": r[2],
                "retrieved": json.loads(r[3]), "draft": r[4],
                "refused": bool(r[5]), "refusal_reason": r[6],
                "provider": r[7], "chat_model": r[8], "latency_ms": r[9],
                "prompt_tokens": r[10], "completion_tokens": r[11],
            }
            for r in rows
        ]


Store = PgStore | SqliteStore


@lru_cache
def get_store() -> Store:
    url = get_settings().database_url
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return PgStore(url)
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///"):]
        path = Path(raw)
        if not path.is_absolute():
            path = REPO_ROOT / raw
        return SqliteStore(path)
    raise ValueError(f"Unsupported DATABASE_URL scheme: {url}")