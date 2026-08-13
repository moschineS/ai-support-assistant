"""Assist pipeline tests: event order, deterministic refusals, citation
validation, audit rows — no network, no Docker."""

from array import array

import pytest

from app.assist import assist_events
from app.config import Settings
from app.db import SqliteStore


class ScriptedGateway:
    """embed() returns a fixed vector; chat_stream() plays a script."""

    def __init__(self, qvec, script=None):
        self.qvec = qvec
        self.script = script
        self.chat_called = False
        self.last_usage = (11, 7)

    def embed(self, texts):
        return [self.qvec for _ in texts]

    def chat_stream(self, system, user):
        self.chat_called = True
        if self.script is None:
            raise AssertionError("chat_stream must not be called in this test")
        yield from self.script


def settings() -> Settings:
    return Settings(openai_embed_model="fake", _env_file=None)


@pytest.fixture
def store(tmp_path):
    st = SqliteStore(tmp_path / "t.db")
    st.ensure_base()
    st.recreate_chunks(dim=4)
    st.insert_chunks(
        [
            {
                "id": "c1", "doc_id": "d1", "doc_title": "pushTAN delays",
                "source_type": "incident", "product": None, "doc_date": "2026-07-14",
                "chunk_index": 0,
                "content": "pushTAN prompts delayed, error EB-1042, use Pending approvals",
                "embedding_blob": array("f", [1, 0, 0, 0]).tobytes(),
                "embedding_literal": "unused",
            }
        ]
    )
    st.set_meta("embedding", {"provider": "openai", "model": "fake", "dim": 4})
    return st


def run(message, store, gateway):
    return list(assist_events(message, store=store, gateway=gateway, s=settings()))


def test_happy_path_streams_and_audits(store):
    gw = ScriptedGateway([1, 0, 0, 0], ["Open Pending approvals", " [S1]."])
    events = run("EB-1042 code not arriving", store, gw)
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    assert "token" in kinds
    meta = events[0][1]
    assert meta["weak"] is False and meta["sources"][0]["label"] == "S1"
    done = events[-1][1]
    assert done["citations"] == ["S1"]
    assert done["usage"] == {"prompt_tokens": 11, "completion_tokens": 7}
    entry = store.audit_recent(1)[0]
    assert entry["refused"] is False and entry["id"] == done["audit_id"]
    assert entry["retrieved"][0]["id"] == "c1"


def test_weak_evidence_refuses_without_llm_call(store):
    gw = ScriptedGateway([0, 0, 0, 1], script=None)  # orthogonal query vector
    events = run("zzqx gibberish", store, gw)
    assert [e for e, _ in events] == ["meta", "refusal"]
    assert events[0][1]["weak"] is True
    assert events[1][1]["reason"] == "weak_evidence"
    assert gw.chat_called is False
    assert store.audit_recent(1)[0]["refusal_reason"] == "weak_evidence"


def test_uncited_draft_is_discarded(store):
    gw = ScriptedGateway([1, 0, 0, 0], ["A draft with no citation at all."])
    events = run("EB-1042 help", store, gw)
    assert events[-1][0] == "refusal"
    assert events[-1][1]["reason"] == "draft_missing_citations"
    entry = store.audit_recent(1)[0]
    assert entry["refused"] is True and entry["draft"] is not None


def test_invalid_citation_is_discarded(store):
    gw = ScriptedGateway([1, 0, 0, 0], ["Claim [S1] and bogus [S9]."])
    events = run("EB-1042 help", store, gw)
    assert events[-1][1]["reason"] == "draft_citation_invalid"
    assert "S9" in events[-1][1]["detail"]


def test_model_reported_gap_becomes_refusal(store):
    gw = ScriptedGateway([1, 0, 0, 0], ["COVERAGE_GAP"])
    events = run("EB-1042 help", store, gw)
    assert events[-1][1]["reason"] == "model_reported_gap"


def test_unseeded_store_refuses(tmp_path):
    st = SqliteStore(tmp_path / "empty.db")
    st.ensure_base()
    gw = ScriptedGateway([1, 0, 0, 0], script=None)
    events = run("anything at all", st, gw)
    assert events == [
        ("refusal", events[0][1]),
    ]
    assert events[0][1]["reason"] == "retrieval_unavailable"
    assert st.audit_recent(1)[0]["refused"] is True