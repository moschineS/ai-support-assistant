"""Retrieval tests: RRF math, fail-closed guards, and hybrid ranking
against a real (temp-file) SQLite store — no network, no Docker."""

from array import array

import pytest

from app.config import Settings
from app.db import SqliteStore
from app.retrieval import RetrievalError, retrieve, rrf_fuse


class FakeGateway:
    """Returns a fixed query vector; embeds nothing for real."""

    def __init__(self, qvec):
        self.qvec = qvec

    def embed(self, texts):
        return [self.qvec for _ in texts]


def settings(embed_model="fake") -> Settings:
    return Settings(openai_embed_model=embed_model, _env_file=None)


CHUNKS = [
    ("c1", "pushTAN approval prompts delayed, error code EB-1042", [1, 0, 0, 0]),
    ("c2", "standing orders and payment schedules explained", [0, 1, 0, 0]),
    ("c3", "mortgage financing with fixed interest periods", [0, 0, 1, 0]),
]


@pytest.fixture
def store(tmp_path):
    st = SqliteStore(tmp_path / "t.db")
    st.ensure_base()
    st.recreate_chunks(dim=4)
    st.insert_chunks(
        [
            {
                "id": cid,
                "doc_id": cid,
                "doc_title": f"Doc {cid}",
                "source_type": "faq",
                "product": None,
                "doc_date": None,
                "chunk_index": 0,
                "content": text,
                "embedding_blob": array("f", vec).tobytes(),
                "embedding_literal": "unused-by-sqlite",
            }
            for cid, text, vec in CHUNKS
        ]
    )
    st.set_meta("embedding", {"provider": "openai", "model": "fake", "dim": 4})
    return st


def test_rrf_prefers_agreement():
    scores = rrf_fuse([["a", "b", "c"], ["b", "a"]])
    assert scores["a"] > scores["c"]
    assert scores["b"] > scores["c"]
    # 'b': rank 2 + rank 1 beats 'a': rank 1 + rank 2 equally
    assert scores["a"] == pytest.approx(scores["b"])


def test_unseeded_store_refuses(tmp_path):
    st = SqliteStore(tmp_path / "empty.db")
    st.ensure_base()
    with pytest.raises(RetrievalError, match="not seeded"):
        retrieve("q", store=st, gateway=FakeGateway([1, 0, 0, 0]), s=settings())


def test_embed_model_mismatch_refuses(store):
    with pytest.raises(RetrievalError, match="seeded with embedding model"):
        retrieve(
            "q", store=store, gateway=FakeGateway([1, 0, 0, 0]),
            s=settings(embed_model="some-other-model"),
        )


def test_hybrid_ranks_semantic_and_keyword_agreement_first(store):
    result = retrieve(
        "customer reports EB-1042 pushTAN code not arriving",
        store=store, gateway=FakeGateway([1, 0, 0, 0]), s=settings(), k=3,
    )
    assert result.hits[0]["id"] == "c1"
    assert result.hits[0]["vector_similarity"] == pytest.approx(1.0)
    assert result.hits[0]["keyword_rank"] == 1
    assert result.keyword_hit is True
    assert not result.is_weak(0.30)


def test_keyword_only_match_still_surfaces(store):
    # Query vector points at c3, but the keyword hits c1: both must rank.
    result = retrieve(
        "EB-1042", store=store, gateway=FakeGateway([0, 0, 1, 0]),
        s=settings(), k=2,
    )
    ids = [h["id"] for h in result.hits]
    assert "c1" in ids and "c3" in ids


def test_weak_evidence_flagged(store):
    result = retrieve(
        "zzqx unrelated gibberish",
        store=store, gateway=FakeGateway([0, 0, 0, 1]), s=settings(), k=3,
    )
    assert result.best_similarity < 0.30
    assert result.keyword_hit is False
    assert result.is_weak(0.30)