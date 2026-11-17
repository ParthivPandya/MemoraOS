"""Evidence fusion: typed multi-hop path search with per-step validation."""

from __future__ import annotations

import pytest

from memoraos import MemoryOS, Scope
from memoraos.config import Settings
from memoraos.fusion import build_evidence_graph, detect_answer_type, evidence_fusion, plan_question
from tests.conftest import FakeClock

U = "user_001"
SCOPE = Scope(tenant_id="default", user_id=U)
Q = "Which Azure region is used by the project Alice manages?"


def chain(m: MemoryOS, user: str = U) -> list[str]:
    ids = []
    for text in ("Alice manages Project Atlas.", "Project Atlas uses Azure Functions.", "Azure Functions is deployed in West Europe."):
        ids.append(m.remember(text, user_id=user, source_type="document").memory_ids[0])
    return ids


def fuse(m: MemoryOS, q: str = Q, when: str | None = None, **kw):
    when = when or m.store.now()
    return evidence_fusion(m.db, SCOPE, q, when=when, **kw)


def test_the_specification_example_resolves_through_three_hops(mem):
    ids = chain(mem)
    r = mem.recall(Q, user_id=U)
    assert (r.status, r.strategy, r.answer) == ("answered", "fusion", "West Europe")
    assert [e.kind for e in r.evidence] == ["path", "path", "path"]
    assert [e.memory_id for e in r.evidence] == ids  # every hop is backed by its own source memory
    assert r.plan.primary == "fusion"
    trace = mem.explain(r.recall_id, user_id=U)
    assert any("Alice -[leads]-> Project Atlas -[uses]-> Azure Functions -[hosted in]-> West Europe" in str(v) for v in trace.values())


def test_confidence_is_the_minimum_over_the_steps(mem):
    mem.remember("Alice manages Project Atlas.", user_id=U, facts=[{"subject": "Alice", "predicate": "leads", "object": "Project Atlas", "confidence": 0.9}])
    mem.remember("Project Atlas uses Azure Functions.", user_id=U, facts=[{"subject": "Project Atlas", "predicate": "uses", "object": "Azure Functions", "confidence": 0.55}])
    mem.remember("Azure Functions is deployed in West Europe.", user_id=U, facts=[{"subject": "Azure Functions", "predicate": "hosted_in", "object": "West Europe", "confidence": 0.8}])
    r = mem.recall(Q, user_id=U)
    assert r.answer == "West Europe" and r.confidence.extraction_confidence == 0.55


def test_reverse_chain_who_leads_the_project_that_uses_a_service(mem):
    chain(mem)
    mem.remember("Bob manages Project Zeta.", user_id=U)
    mem.remember("Project Zeta uses Cosmos DB.", user_id=U)
    r = mem.recall("Who manages the project that uses Azure Functions?", user_id=U)
    assert (r.status, r.strategy, r.answer) == ("answered", "fusion", "Alice")


def test_a_fact_of_the_wrong_kind_never_answers_the_question(mem):
    mem.remember("Alice manages Project Atlas.", user_id=U)
    r = mem.recall(Q, user_id=U)
    assert r.status == "insufficient_evidence" and "Atlas" not in r.answer
    assert detect_answer_type(Q).name == "region"
    assert mem.recall("Which region does Alice use?", user_id=U).status == "insufficient_evidence"


def test_a_missing_link_is_insufficient_not_a_guess(mem):
    mem.remember("Alice manages Project Atlas.", user_id=U)
    mem.remember("Azure Functions is deployed in West Europe.", user_id=U)  # nothing says Atlas uses it
    assert mem.recall(Q, user_id=U).status == "insufficient_evidence"


def test_conflicting_terminal_facts_are_reported_not_resolved(mem):
    chain(mem)
    mem.remember("Azure Functions is deployed in North Europe.", user_id=U, source_type="document")
    r = mem.recall(Q, user_id=U)
    assert r.status == "conflict" and "West Europe" in r.answer and "North Europe" in r.answer
    assert all("conflicting_value" in e.flags for e in r.evidence[-2:])


def test_a_more_reliable_later_statement_resolves_the_terminal_conflict(mem):
    chain(mem)
    mem.remember("Azure Functions is deployed in North Europe.", user_id=U, source_type="user_statement")
    r = mem.recall(Q, user_id=U, use_cache=False)
    assert (r.status, r.strategy, r.answer) == ("answered", "fusion", "North Europe")


def test_several_valid_chains_to_different_answers_are_ambiguous_not_answered(mem):
    chain(mem)
    mem.remember("Project Atlas uses Blob Storage.", user_id=U, source_type="document")
    mem.remember("Blob Storage is deployed in North Europe.", user_id=U, source_type="document")
    r = mem.recall(Q, user_id=U)
    assert r.status == "conflict" and "West Europe" in r.answer and "North Europe" in r.answer
    assert "several different chains" in r.answer


def test_expired_relations_do_not_connect_the_chain(mem):
    mem.remember("Alice leads Project Atlas.", user_id=U, facts=[{"subject": "Alice", "predicate": "leads", "object": "Project Atlas", "valid_from": "2020-01-01", "valid_until": "2023-12-31"}])
    mem.remember("Project Atlas uses Azure Functions.", user_id=U, facts=[{"subject": "Project Atlas", "predicate": "uses", "object": "Azure Functions", "valid_from": "2020-01-01"}])
    mem.remember("Azure Functions is deployed in West Europe.", user_id=U, facts=[{"subject": "Azure Functions", "predicate": "hosted_in", "object": "West Europe", "valid_from": "2020-01-01"}])
    assert mem.recall(Q, user_id=U, use_cache=False).status == "insufficient_evidence"
    # system time still matters: nothing had been recorded yet in mid-2022, so the past is unknown rather than guessed
    assert mem.recall(Q, user_id=U, as_of="2022-06-01", use_cache=False).status == "insufficient_evidence"


def test_valid_time_is_respected_when_system_time_allows(mem, clock):
    clock.jump(days=4000)  # recorded far in the future relative to the facts' own validity
    mem.remember("x placeholder note", user_id=U)
    mem.remember("Alice leads Project Atlas.", user_id=U, facts=[{"subject": "Alice", "predicate": "leads", "object": "Project Atlas", "valid_from": "2020-01-01", "valid_until": "2023-12-31"}])
    mem.remember("Project Atlas uses Azure Functions.", user_id=U, facts=[{"subject": "Project Atlas", "predicate": "uses", "object": "Azure Functions", "valid_from": "2020-01-01"}])
    mem.remember("Azure Functions is deployed in West Europe.", user_id=U, facts=[{"subject": "Azure Functions", "predicate": "hosted_in", "object": "West Europe", "valid_from": "2020-01-01"}])
    now = mem.store.now()
    assert fuse(mem, when=now).status == "insufficient_evidence"  # Alice's leadership ended in 2023
    assert fuse(mem, when="2022-06-01T00:00:00.000000Z").answer == "West Europe"


def test_negating_a_link_breaks_the_chain(mem):
    chain(mem)
    assert mem.recall(Q, user_id=U).answer == "West Europe"
    mem.remember("Alice does not manage Project Atlas.", user_id=U)
    assert mem.recall(Q, user_id=U, use_cache=False).status == "insufficient_evidence"


def test_correcting_a_link_changes_the_answer(mem):
    ids = chain(mem)
    mem.correct(ids[2], "Azure Functions is deployed in Sweden Central.", user_id=U)
    assert mem.recall(Q, user_id=U, use_cache=False).answer == "Sweden Central"


def test_other_users_facts_are_never_used(mem):
    chain(mem, user="someone_else")
    assert mem.recall(Q, user_id=U).status == "insufficient_evidence"


def test_cycles_terminate_and_never_revisit_an_entity(mem):
    for t in ("Alice manages Project Atlas.", "Project Atlas uses Service A.", "Service A uses Service B.", "Service B uses Service A.", "Service B uses Service C.", "Service C is deployed in Pune."):
        mem.remember(t, user_id=U)
    res = fuse(mem, max_hops=6)
    assert res.status == "answered" and res.values == ["Pune"]
    for p in res.paths:
        nodes = [p.steps[0].start] + [s.end for s in p.steps]
        assert len(nodes) == len(set(nodes))
    mem.remember("Service C uses Project Atlas.", user_id=U)  # a cycle back to the anchor
    assert fuse(mem, max_hops=6).values == ["Pune"]
    assert fuse(mem).status == "insufficient_evidence"  # the default hop bound (4) is respected


def test_search_size_is_bounded_and_reports_truncation(mem):
    letters = "abcdefghijkl"
    mem.remember("Alice manages Project Atlas.", user_id=U)
    for a in letters:
        mem.remember(f"Project Atlas uses Svc{a}.", user_id=U)
        for b in letters:
            mem.remember(f"Svc{a} uses Part{a}{b}.", user_id=U)
    mem.remember("Partaa is deployed in Pune.", user_id=U)
    small = fuse(mem, max_expansions=100)
    assert small.truncated and any("stopped at its bound" in n for n in small.notes)
    capped = fuse(mem, max_paths=1)
    assert len(capped.paths) <= 1
    full = fuse(mem)
    assert full.values == ["Pune"] and not full.truncated


def test_plan_requires_a_chain_not_a_single_fact(mem):
    chain(mem)
    g = build_evidence_graph(mem.db, SCOPE, mem.store.now())
    assert plan_question(Q, g.nodes).applicable
    assert not plan_question("Which database does Atlas use?", g.nodes).applicable  # one hop answers it
    assert not plan_question("What is the capital of France?", g.nodes).applicable
    assert not plan_question("Which region hosts billing?", g.nodes).applicable  # names no anchor relation
    p = plan_question(Q, g.nodes)
    assert p.anchors == ["alice"] and (p.cue.predicate, p.cue.direction) == ("leads", "out") and p.answer.name == "region"


def test_ordinary_questions_do_not_use_fusion(mem):
    chain(mem)
    mem.remember("The database of Project Atlas is PostgreSQL.", user_id=U)
    assert mem.recall("Which database does Atlas use?", user_id=U).strategy != "fusion"
    assert mem.recall("Who manages Project Atlas?", user_id=U).strategy != "fusion"


def test_fusion_can_be_disabled():
    m = MemoryOS.in_memory(settings=Settings(evidence_fusion=False), clock=FakeClock())
    try:
        chain(m)
        r = m.recall(Q, user_id=U)
        assert "fusion" not in r.plan.stages and r.strategy != "fusion"
        assert r.status == "insufficient_evidence"  # without the chain search nothing else can prove the answer
    finally:
        m.close()


def test_forced_fusion_strategy_and_unknown_answer_type(mem):
    chain(mem)
    assert mem.recall(Q, user_id=U, strategy="fusion").answer == "West Europe"
    r = mem.recall("What is the capital of France?", user_id=U, strategy="fusion")
    assert r.status == "insufficient_evidence"


@pytest.mark.parametrize(
    ("q", "name"),
    [("Which Azure region hosts billing?", "region"), ("Who leads Atlas?", "lead"), ("Where does Priya live?", "residence"), ("Where does Priya work?", "employer"), ("Which database does Atlas use?", "database")],
)
def test_answer_types(q, name):
    assert detect_answer_type(q).name == name
