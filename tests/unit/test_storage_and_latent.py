import sqlite3

import numpy as np
import pytest

from memoraos import MemoryOS, Scope
from memoraos.config import Settings
from memoraos.evaluation import mrr, ndcg_at_k, precision_at_k, recall_at_k
from memoraos.evaluation.metrics import answer_correct
from memoraos.latent import SlotAttentionMemory, evaluate_information_preservation, memorilla_available
from memoraos.storage import Database, visibility_clause, write_scope_id


def test_migrations_are_idempotent_and_versioned(tmp_path):
    db = Database(tmp_path / "x.db")
    assert db.schema_version == 1 and db.migrate() == []
    db.close()
    assert Database(tmp_path / "x.db").schema_version == 1


def test_transactions_roll_back_and_nest():
    db = Database(":memory:")
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            c.execute("INSERT INTO audit_log(ts, tenant_id, action) VALUES('t','x','a')")
            raise RuntimeError
    assert db.one("SELECT COUNT(*) FROM audit_log")[0] == 0
    with db.tx() as c:
        with db.tx():
            c.execute("INSERT INTO audit_log(ts, tenant_id, action) VALUES('t','x','a')")
    assert db.one("SELECT COUNT(*) FROM audit_log")[0] == 1


def test_online_backup_is_restorable(tmp_path):
    m = MemoryOS.local(tmp_path / "d")
    m.remember("Parth's salary is ₹32 LPA.", user_id="u")
    dest = m.backup(tmp_path / "bk" / "copy.db")
    m.close()
    con = sqlite3.connect(dest)
    assert con.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    con.close()


def test_visibility_clause_levels():
    s = Scope(tenant_id="t", user_id="u", agent_id="a", project_id="p")
    sql, params = visibility_clause(s, "m")
    assert sql.count("?") == len(params) and "scope_level='org'" in sql and "m.scope_id=?" in sql
    assert write_scope_id(s, "user") == "u" and write_scope_id(s, "org") == "t" and write_scope_id(s, "agent") == "a"
    with pytest.raises(ValueError):
        write_scope_id(s, "session")
    with pytest.raises(ValueError):
        Scope(user_id=" ")


def test_settings_validation():
    with pytest.raises(ValueError):
        Settings(chunk_chars=200, chunk_overlap=200)
    with pytest.raises(ValueError):
        Settings(default_top_k=0)


def test_ranking_metrics():
    ranked, rel = ["a", "b", "c", "d"], {"b", "d"}
    assert recall_at_k(ranked, rel, 2) == 0.5 and precision_at_k(ranked, rel, 2) == 0.5
    assert mrr(ranked, rel) == 0.5 and 0 < ndcg_at_k(ranked, rel, 4) < 1
    assert ndcg_at_k(["b", "d"], rel, 2) == pytest.approx(1.0)
    assert answer_correct("It is ₹32 LPA", "₹32 LPA", ["₹28 LPA"]) and not answer_correct("₹32 LPA or ₹28 LPA", "₹32 LPA", ["₹28 LPA"])


def test_latent_slot_memory_keeps_documents_recoverable_and_is_deterministic():
    rng = np.random.default_rng(0)
    centers = rng.normal(size=(4, 32))
    docs = np.vstack([centers[i % 4] + 0.05 * rng.normal(size=32) for i in range(40)]).astype(np.float32)
    docs /= np.linalg.norm(docs, axis=1, keepdims=True)
    ids = [f"d{i}" for i in range(40)]
    a, b = SlotAttentionMemory(n_slots=4), SlotAttentionMemory(n_slots=4)
    a.fit(ids, docs)
    b.fit(ids, docs)
    assert np.allclose(a.slots, b.slots)
    assert a.readout(docs[0]).shape == (4, 32) and a.stats().compression_ratio == 10
    top = [d for d, _ in a.retrieve(docs[5], 5)]
    assert "d5" in top and all(t in ids for t in top)  # always points back at source documents
    result = evaluate_information_preservation(SlotAttentionMemory(n_slots=4), ids, docs, docs[:8], ids[:8], k=10)
    assert result["n_slots"] == 4 and 0 <= result["recall_at_k_latent"] <= 1 and result["recall_at_k_exact_cosine"] == 1.0
    assert "experimental" in result["backend"]


def test_latent_is_optional_and_does_not_claim_memorilla():
    assert memorilla_available() is False
    m = MemoryOS.in_memory()
    m.remember("Zephyr tracks rocket telemetry with Rust.", user_id="u")
    res = m.recall("telemetry", user_id="u", strategy="latent")
    assert res.status == "insufficient_evidence" and "not configured" in str(m.explain(res.recall_id, user_id="u")["attempts"])
    m.enable_latent(n_slots=2)
    assert m.recall("rocket telemetry", user_id="u", strategy="latent").status == "answered"
