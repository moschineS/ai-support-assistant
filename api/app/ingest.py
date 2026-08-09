"""Corpus ingestion: frontmatter parse -> heading-aware chunking -> embed -> pgvector.

Run from the ``api/`` directory:

    python -m app.ingest [--corpus ../corpus]

The seed is idempotent: it recreates the ``chunks`` table every run (the
corpus is the source of truth, the table is derived state) and records the
active ``(provider, model, dim)`` in ``meta``. The API refuses to answer
when the running embedding provider disagrees with the seeded one — a
768-dim query against 1536-dim vectors must be a hard error, not a silent
wrong answer (ADR-005).

Chunking is heading-aware rather than fixed-window: support documents are
short and well-structured, so ``##`` sections are the natural retrieval
unit. Every chunk is prefixed with a ``[title - section]`` breadcrumb so
the embedded text and the keyword index both carry the document context.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

from . import db
from .config import REPO_ROOT, get_settings
from .gateway import get_gateway

MAX_CHUNK_CHARS = 3000   # ~750 tokens; sections are usually far smaller
MIN_CHUNK_CHARS = 300    # merge tiny sections into their predecessor
OVERLAP_CHARS = 400      # tail carried over when a long section is split
EMBED_BATCH = 32


@dataclass
class Doc:
    doc_id: str
    title: str
    source_type: str
    product: str | None
    date: dt.date | None
    body: str


@dataclass
class Chunk:
    doc: Doc
    chunk_index: int
    content: str

    @property
    def chunk_id(self) -> str:
        return f"{self.doc.doc_id}#{self.chunk_index}"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse a minimal ``--- key: value ---`` block. No YAML dependency —
    the corpus format is ours and flat key/value is all it needs."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("document is missing a frontmatter block")
    meta: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i].strip()
        if line and ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"')
        i += 1
    body = "\n".join(lines[i + 1 :]).strip()
    return meta, body


def load_doc(path: Path) -> Doc:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    for required in ("id", "title", "type"):
        if required not in meta:
            raise ValueError(f"{path.name}: frontmatter missing '{required}'")
    date = dt.date.fromisoformat(meta["date"]) if meta.get("date") else None
    return Doc(
        doc_id=meta["id"],
        title=meta["title"],
        source_type=meta["type"],
        product=meta.get("product") or None,
        date=date,
        body=body,
    )


def _split_long(text: str) -> list[str]:
    """Split an over-long section at paragraph boundaries with overlap."""
    paragraphs = text.split("\n\n")
    parts: list[str] = []
    current = ""
    for p in paragraphs:
        candidate = f"{current}\n\n{p}".strip()
        if len(candidate) > MAX_CHUNK_CHARS and current:
            parts.append(current)
            current = (current[-OVERLAP_CHARS:] + "\n\n" + p).strip()
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def chunk_doc(doc: Doc) -> list[Chunk]:
    # Split the body into (section_heading, section_text) pairs on '## '.
    sections: list[tuple[str, str]] = []
    heading = ""
    buf: list[str] = []
    for line in doc.body.splitlines():
        if line.startswith("## "):
            if buf and "".join(buf).strip():
                sections.append((heading, "\n".join(buf).strip()))
            heading = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        sections.append((heading, "\n".join(buf).strip()))

    # Merge tiny sections forward, split oversized ones.
    texts: list[str] = []
    for heading, text in sections:
        breadcrumb = f"[{doc.title}" + (f" - {heading}]" if heading else "]")
        piece = f"{breadcrumb}\n{text}"
        if texts and len(piece) < MIN_CHUNK_CHARS:
            texts[-1] = f"{texts[-1]}\n\n{piece}"
        elif len(piece) > MAX_CHUNK_CHARS:
            texts.extend(f"{breadcrumb}\n{part}" for part in _split_long(text))
        else:
            texts.append(piece)

    return [Chunk(doc=doc, chunk_index=i, content=t) for i, t in enumerate(texts)]


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def seed(corpus_dir: Path) -> None:
    s = get_settings()
    gateway = get_gateway(s)
    embed_model = (
        s.ollama_embed_model if s.provider == "ollama" else s.openai_embed_model
    )

    paths = sorted(corpus_dir.glob("*.md"))
    if not paths:
        print(f"ERROR: no .md documents found in {corpus_dir}")
        sys.exit(1)

    docs = [load_doc(p) for p in paths]
    chunks = [c for d in docs for c in chunk_doc(d)]
    print(f"Corpus: {len(docs)} documents -> {len(chunks)} chunks")

    print(f"Embedding with {s.provider}/{embed_model} ...")
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i : i + EMBED_BATCH]
        vectors.extend(gateway.embed([c.content for c in batch]))
        print(f"  embedded {min(i + EMBED_BATCH, len(chunks))}/{len(chunks)}")
    dim = len(vectors[0])

    store = db.get_store()
    store.ensure_base()
    store.recreate_chunks(dim)
    store.insert_chunks(
        [
            {
                "id": c.chunk_id,
                "doc_id": c.doc.doc_id,
                "doc_title": c.doc.title,
                "source_type": c.doc.source_type,
                "product": c.doc.product,
                "doc_date": c.doc.date.isoformat() if c.doc.date else None,
                "chunk_index": c.chunk_index,
                "content": c.content,
                # Each backend picks the representation it binds:
                "embedding_literal": vector_literal(v),
                "embedding_blob": array("f", v).tobytes(),
            }
            for c, v in zip(chunks, vectors, strict=True)
        ]
    )
    store.set_meta(
        "embedding",
        {
            "provider": s.provider,
            "model": embed_model,
            "dim": dim,
            "seeded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "docs": len(docs),
            "chunks": len(chunks),
        },
    )

    print(
        f"Seeded: {len(chunks)} chunks, dim={dim},"
        f" provider={s.provider}, backend={store.backend}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the support corpus")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPO_ROOT / "corpus",
        help="directory of markdown documents (default: <repo>/corpus)",
    )
    args = parser.parse_args()
    seed(args.corpus.resolve())


if __name__ == "__main__":
    main()