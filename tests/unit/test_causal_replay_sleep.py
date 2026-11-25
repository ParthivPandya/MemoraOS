from __future__ import annotations

import pytest

from memoraos import MemoryOS
from memoraos.engine import NotFoundError

U = "user_001"


@pytest.fixture()
def mem():
    m = MemoryOS.in_memory()
    yield m
    m.close()


def _mid(mem, text, **kw):
    return mem.remember(text, user_id=U, **kw).memory_ids[0]


def test_links_build_a_lineage_with_hashes(mem):
    a = _mid(mem, "The deploy failed because the config file was missing.")
    b = _mid(mem, "Restoring config.yaml fixed the deploy.")
    c = _mid(mem, "Deploys now run a config check first.")
    mem.link(a, b, "solves", user_id=U)
    mem.link(b, c, "causes", user_id=U)
    lin = mem.lineage(c, user_id=U, direction="up")
    assert [n["memory_id"] for n in lin["nodes"]] == [c, b, a]
    assert {(e["src"], e["dst"], e["kind"]) for e in lin["edges"]} == {(a, b, "solves"), (b, c, "causes")}
    stored = mem.get(a, user_id=U).original_content
    from memoraos.util import sha256

    assert next(n for n in lin["nodes"] if n["memory_id"] == a)["content_sha256"] == sha256(stored)
    assert [n["memory_id"] for n in mem.lineage(a, user_id=U, direction="down", max_depth=1)["nodes"]] == [a, b]


def test_link_validation_and_unlink(mem):
    a = _mid(mem, "Alpha happened.")
    b = _mid(mem, "Beta happened.")
    with pytest.raises(ValueError):
        mem.link(a, b, "inspires", user_id=U)
    with pytest.raises(ValueError):
        mem.link(a, a, "causes", user_id=U)
    with pytest.raises(NotFoundError):
        mem.link(a, "mem_missing", "causes", user_id=U)
    mem.link(a, b, "causes", user_id=U)
    assert mem.unlink(a, b, "causes", user_id=U) is True
    assert mem.lineage(b, user_id=U)["edges"] == []


def test_lineage_never_reveals_other_users_memories(mem):
    mine = _mid(mem, "My note about the outage.")
    theirs = mem.remember("Their private note.", user_id="other_user").memory_ids[0]
    mem.db.execute(
        "INSERT INTO memory_links(src_id,dst_id,type,run_id,tenant_id,created_at) VALUES(?,?,?,?,?,?)",
        (theirs, mine, "causal:causes", None, "default", "2026-01-01T00:00:00Z"),
    )
    lin = mem.lineage(mine, user_id=U, direction="up")
    assert [n["memory_id"] for n in lin["nodes"]] == [mine] and lin["edges"] == []


def test_forgetting_a_memory_removes_its_edges(mem):
    a = _mid(mem, "Cause memory.")
    b = _mid(mem, "Effect memory.")
    mem.link(a, b, "causes", user_id=U)
    mem.forget(a, user_id=U)
    assert mem.lineage(b, user_id=U)["edges"] == []


def test_replay_shows_dependence_without_touching_the_live_store(mem):
    old = _mid(mem, "The customer plan is Professional.", effective_at="2026-01-01")
    new = _mid(mem, "The customer plan is Enterprise.", effective_at="2026-06-01")
    res = mem.recall("What is the customer plan?", user_id=U)
    assert "Enterprise" in res.answer
    rep = mem.replay(res.recall_id, user_id=U, exclude=[new])
    assert rep["baseline_matches_logged"] is True
    run = rep["runs"][0]
    assert run["answer_changed"] is True and "Enterprise" not in run["answer"]
    # the live store still has both memories and still answers the same way
    assert {m.id for m in mem.list_memories(user_id=U)} == {old, new}
    assert "Enterprise" in mem.recall("What is the customer plan?", user_id=U, use_cache=False).answer


def test_replay_leave_one_out_and_validation(mem):
    _mid(mem, "The office is in Pune.")
    res = mem.recall("Where is the office?", user_id=U)
    rep = mem.replay(res.recall_id, user_id=U, leave_one_out=True)
    assert len(rep["runs"]) == len({e.memory_id for e in res.evidence}) >= 1
    with pytest.raises(ValueError):
        mem.replay(res.recall_id, user_id=U)
    with pytest.raises(NotFoundError):
        mem.replay("rec_missing", user_id=U, exclude=["x"])
    with pytest.raises(NotFoundError):
        mem.replay(res.recall_id, user_id="someone_else", exclude=["x"])


def test_sleep_expires_only_old_hypotheses_and_dry_run_is_inert(mem):
    h = mem.remember_outcome("run the migration twice", "failed", user_id=U).memory_ids[0]
    v = mem.remember_outcome("pin the dependency", "failed", user_id=U, evidence_ref="ci-run-1").memory_ids[0]
    assert mem.sleep(user_id=U, expire_hypotheses_days=1)["expired_hypotheses"] == []  # not old enough
    from datetime import datetime, timedelta, timezone

    mem.clock = lambda: datetime.now(timezone.utc) + timedelta(days=3)
    dry = mem.sleep(user_id=U, expire_hypotheses_days=1, dry_run=True, consolidate=False)
    assert dry["expired_hypotheses"] == [h] and mem.get(h, user_id=U).verification == "hypothesis"
    done = mem.sleep(user_id=U, expire_hypotheses_days=1, consolidate=False)
    assert done["expired_hypotheses"] == [h] and done["audit_chain_ok"] is True
    assert mem.get(h, user_id=U).verification == "disputed" and mem.get(v, user_id=U).verification == "verified"
    with pytest.raises(ValueError):
        mem.sleep(user_id=U, expire_hypotheses_days=0)
