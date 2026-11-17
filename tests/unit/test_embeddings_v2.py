"""Embedding provider v2: metadata, guards against mixed models, re-embedding and index rebuilds."""

from __future__ import annotations

import sys

import numpy as np
import pytest

from memoraos import MemoryOS, Scope
from memoraos.config import Settings
from memoraos.providers import (
    BaseEmbeddingProvider,
    EmbeddingModelMismatch,
    HashingEmbedder,
    ProviderError,
    ProviderUnavailable,
    SentenceTransformerEmbedder,
    adapt_embedder,
)
from tests.conftest import FakeClock

U = "user_001"
SCOPE = Scope(tenant_id="default", user_id=U)
GROUPS = [{"car", "automobile", "vehicle"}, {"salary", "pay", "compensation"}]


class ConceptEmbedder(BaseEmbeddingProvider):
    """A stand-in for a neural embedder: words of one concept group share a direction."""

    provider = "fake-neural"

    def __init__(self, name: str = "concept-a", dim: int = 32, version: str = "1"):
        self.name, self.dim, self.model_version = name, dim, version
        self.fail = False
        self.calls = 0

    def embed_batch(self, texts):
        self.calls += 1
        if self.fail:
            raise ProviderError("provider down")
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().replace(".", "").split():
                gid = next((j for j, g in enumerate(GROUPS) if w in g), None)
                key = f"g{gid}" if gid is not None else w
                out[i, hash(key) % self.dim] += 1.0
            n = np.linalg.norm(out[i])
            out[i] /= n or 1.0
        return out


class LegacyProvider:
    """A v0.1-style provider: only name, dim and embed()."""

    name = "legacy-x"
    dim = 16

    def embed(self, texts):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                out[i, hash(w) % self.dim] += 1.0
            out[i] /= np.linalg.norm(out[i]) or 1.0
        return out


def new_mem(embedder, tmp_path=None, **settings) -> MemoryOS:
    kw = {"clock": FakeClock()}
    s = Settings(**settings) if settings else None
    if tmp_path is not None:
        return MemoryOS.local(tmp_path, embedder=embedder, settings=s, **kw)
    return MemoryOS.in_memory(embedder=embedder, settings=s, **kw)


def top_ids(m: MemoryOS, q: str) -> list[str]:
    return [c.memory_id for c in m.vectors.search(SCOPE, q, 5, min_score=0.2)]


def test_v2_interface_and_model_info():
    e = ConceptEmbedder()
    assert e.embed_text("a car").shape == (32,)
    assert e.embed_batch(["a", "b"]).shape == (2, 32) and np.array_equal(e.embed(["a"]), e.embed_batch(["a"]))
    info = e.get_model_info()
    assert (info.model, info.provider, info.dim, info.version, info.normalization) == ("concept-a", "fake-neural", 32, "1", "l2")
    assert e.get_embedding_dimension() == 32
    assert e.health_check().ok
    h = HashingEmbedder(64)
    assert h.get_model_info().dim == 64 and h.embed_text("x").shape == (64,)


def test_health_check_reports_failure_instead_of_raising():
    e = ConceptEmbedder()
    e.fail = True
    status = e.health_check()
    assert not status.ok and "provider down" in status.detail


def test_legacy_providers_are_adapted_and_still_work_end_to_end():
    a = adapt_embedder(LegacyProvider())
    assert isinstance(a, BaseEmbeddingProvider) and a.get_model_info().model == "legacy-x" and a.embed_text("hi").shape == (16,)
    assert adapt_embedder(a) is a
    with pytest.raises(TypeError):
        adapt_embedder(object())
    m = new_mem(LegacyProvider())
    try:
        m.remember("Alice leads Project Atlas.", user_id=U)
        assert m.recall("Who leads Project Atlas?", user_id=U).answer == "Alice"
        assert m.health()["embedder"] == "legacy-x"
    finally:
        m.close()


def test_embedding_metadata_and_registry_are_persisted():
    m = new_mem(ConceptEmbedder())
    try:
        m.remember("The automobile is red.", user_id=U)
        row = m.db.one("SELECT provider, model_version, normalization, status, created_at, dim FROM embeddings WHERE model='concept-a'")
        assert (row["provider"], row["model_version"], row["normalization"], row["status"], row["dim"]) == ("fake-neural", "1", "l2", "ready", 32)
        assert row["created_at"]
        reg = m.db.one("SELECT * FROM embedding_models WHERE model='concept-a'")
        assert reg["active"] == 1 and reg["dim"] == 32 and reg["provider"] == "fake-neural"
        info = m.embedding_info(deep=True)
        assert info["active"]["model"] == "concept-a" and info["health"]["ok"]
        assert m.health(deep=True)["status"] == "ok"
    finally:
        m.close()


def test_deep_health_degrades_when_the_embedder_is_down():
    e = ConceptEmbedder()
    m = new_mem(e)
    try:
        e.fail = True
        assert m.health(deep=True)["status"] == "degraded" and m.health()["status"] == "ok"
    finally:
        m.close()


def test_same_model_name_with_a_different_dimension_is_refused(tmp_path):
    m = new_mem(ConceptEmbedder(dim=32), tmp_path)
    m.remember("The automobile is red.", user_id=U)
    m.close()
    m2 = new_mem(ConceptEmbedder(dim=64), tmp_path)
    try:
        with pytest.raises(EmbeddingModelMismatch, match="32"):
            m2.remember("Another note about pay.", user_id=U)
        assert m2.db.one("SELECT COUNT(*) FROM memories")[0] == 1  # nothing half-written
    finally:
        m2.close()


def test_mismatch_can_be_resolved_by_reindexing_automatically(tmp_path):
    m = new_mem(ConceptEmbedder(dim=32), tmp_path)
    m.remember("The automobile is red.", user_id=U)
    m.close()
    m2 = new_mem(ConceptEmbedder(dim=64), tmp_path, embedding_on_mismatch="reindex")
    try:
        m2.remember("A vehicle was parked.", user_id=U)
        assert len(top_ids(m2, "car")) == 2  # old memory was re-embedded at 64 dims, not left at 32
        assert {r["dim"] for r in m2.db.query("SELECT dim FROM embeddings")} == {64}
    finally:
        m2.close()


def test_a_new_model_version_discards_the_old_vectors_and_rebuilds_lazily(tmp_path):
    m = new_mem(ConceptEmbedder(version="1"), tmp_path)
    m.remember("The automobile is red.", user_id=U)
    m.close()
    m2 = new_mem(ConceptEmbedder(version="2"), tmp_path)
    try:
        assert len(top_ids(m2, "car")) == 1
        assert {r["model_version"] for r in m2.db.query("SELECT model_version FROM embeddings WHERE model='concept-a'")} == {"2"}
    finally:
        m2.close()


def test_switching_models_never_mixes_vectors_and_reembed_migrates_everything(tmp_path):
    old = new_mem(HashingEmbedder(64), tmp_path)
    old.remember("The automobile is red.", user_id=U)
    old.remember("Quarterly pay review is scheduled.", user_id=U)
    old.close()
    neural = ConceptEmbedder("concept-b")
    m = new_mem(neural, tmp_path)
    try:
        assert top_ids(m, "car")  # lazy backfill happens on first search
        assert m.db.one("SELECT COUNT(*) FROM memories WHERE embedding_model != 'concept-b'")[0] == 0
        m.db.execute("UPDATE memories SET embedding_model='hashing-v1'")  # simulate not-yet-migrated rows
        report = m.reembed()
        assert report["embedded"] == 2 and report["failed"] == 0 and report["model"] == "concept-b"
        assert m.db.one("SELECT COUNT(*) FROM embeddings WHERE model='hashing-v1' AND status='stale'")[0] == 2  # kept for rollback
        assert m.reembed()["embedded"] == 0  # idempotent
        assert m.reembed(prune_stale=True)["failed"] == 0
        assert m.db.one("SELECT COUNT(*) FROM embeddings WHERE model='hashing-v1'")[0] == 0
        assert len(top_ids(m, "compensation")) >= 1  # semantic match through the new model
    finally:
        m.close()


def test_reembed_survives_a_provider_outage_and_finishes_on_retry(tmp_path):
    base = new_mem(HashingEmbedder(64), tmp_path)
    for i in range(5):
        base.remember(f"Note {i} about the automobile.", user_id=U)
    base.close()
    e = ConceptEmbedder("concept-c")
    m = new_mem(e, tmp_path)
    try:
        e.fail = True
        r = m.reembed(batch_size=2)
        assert r["failed"] == 5 and r["embedded"] == 0 and "provider down" in r["errors"][0]
        assert m.db.one("SELECT COUNT(*) FROM embeddings WHERE status='stale'")[0] == 0  # nothing marked stale after a failure
        e.fail = False
        r2 = m.reembed(batch_size=2)
        assert r2["embedded"] == 5 and r2["failed"] == 0
        assert m.recall("What is note 3 about?", user_id=U, use_cache=False).status in {"answered", "insufficient_evidence"}
    finally:
        m.close()


def test_forced_reembed_recomputes_everything_for_the_current_model():
    e = ConceptEmbedder()
    m = new_mem(e)
    try:
        m.remember("The automobile is red.", user_id=U)
        calls = e.calls
        assert m.reembed()["embedded"] == 0 and e.calls == calls
        r = m.reembed(force=True)
        assert r["embedded"] == 1 and r["forced"] and e.calls > calls
    finally:
        m.close()


def test_rebuild_index_restores_the_full_text_index():
    m = new_mem(ConceptEmbedder())
    try:
        m.remember("Alice leads Project Atlas.", user_id=U)
        m.db.execute("DELETE FROM memories_fts")
        assert m.recall("Atlas", user_id=U, strategy="bm25", use_cache=False).status != "answered"
        rep = m.rebuild_index()
        assert rep["fts_rows"] == 1
        assert "Alice" in m.recall("Who leads Project Atlas?", user_id=U, strategy="bm25", use_cache=False).answer
    finally:
        m.close()


def test_sentence_transformer_adapter_with_an_injected_model():
    class FakeST:
        def get_sentence_embedding_dimension(self):
            return 4

        def encode(self, texts, **kw):
            assert kw["normalize_embeddings"] is True
            return np.tile(np.array([[1, 0, 0, 0]], dtype=np.float32), (len(texts), 1))

    e = SentenceTransformerEmbedder("fake/model", model=FakeST(), revision="abc")
    info = e.get_model_info()
    assert (info.model, info.provider, info.dim, info.version) == ("st:fake/model", "sentence-transformers", 4, "abc")
    assert e.embed_batch(["a", "b"]).shape == (2, 4) and e.embed_batch([]).shape == (0, 4)


def test_sentence_transformer_is_lazy_and_reports_a_missing_dependency(monkeypatch):
    e = SentenceTransformerEmbedder("x/y")  # construction must not import or download anything
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ProviderUnavailable, match="pip install"):
        e.embed_batch(["hello"])
    assert not e.health_check().ok
