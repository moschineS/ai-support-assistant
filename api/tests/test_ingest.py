"""Chunker and frontmatter tests."""

import pytest

from app.ingest import (
    MAX_CHUNK_CHARS,
    Doc,
    chunk_doc,
    parse_frontmatter,
    vector_literal,
)


def make_doc(body: str) -> Doc:
    return Doc(
        doc_id="d1",
        title="Test document",
        source_type="faq",
        product=None,
        date=None,
        body=body,
    )


def test_parse_frontmatter_roundtrip():
    meta, body = parse_frontmatter(
        '---\nid: x\ntitle: "Quoted title"\ntype: faq\n---\n\nBody text.'
    )
    assert meta == {"id": "x", "title": "Quoted title", "type": "faq"}
    assert body == "Body text."


def test_parse_frontmatter_missing_block_raises():
    with pytest.raises(ValueError):
        parse_frontmatter("no frontmatter here")


def test_chunks_follow_h2_sections_with_breadcrumbs():
    body = (
        "Intro paragraph that is long enough to stand on its own as a chunk"
        " because it exceeds the minimum chunk size threshold set in the"
        " ingestion module, which merges tiny fragments forward. " * 3
        + "\n\n## First section\n"
        + "Content of the first section. " * 20
        + "\n\n## Second section\n"
        + "Content of the second section. " * 20
    )
    chunks = chunk_doc(make_doc(body))
    assert len(chunks) == 3
    assert chunks[0].content.startswith("[Test document]")
    assert chunks[1].content.startswith("[Test document - First section]")
    assert chunks[2].content.startswith("[Test document - Second section]")
    assert [c.chunk_id for c in chunks] == ["d1#0", "d1#1", "d1#2"]


def test_tiny_section_merges_into_predecessor():
    body = (
        "## Long section\n" + "Plenty of content here. " * 30
        + "\n\n## Tiny\nShort."
    )
    chunks = chunk_doc(make_doc(body))
    assert len(chunks) == 1
    assert "Tiny" in chunks[0].content and "Short." in chunks[0].content


def test_long_section_splits_under_limit():
    body = "## Big section\n" + ("A paragraph of filler text. " * 30 + "\n\n") * 12
    chunks = chunk_doc(make_doc(body))
    assert len(chunks) >= 2
    assert all(len(c.content) <= MAX_CHUNK_CHARS + 200 for c in chunks)


def test_vector_literal_format():
    assert vector_literal([0.25, -1.0]) == "[0.25,-1]"