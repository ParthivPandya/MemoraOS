import pytest

from memoraos import NotFoundError
from memoraos.providers.base import ChatResponse, ProviderUnavailable, Usage

U = "u1"


class FakeChat:
    name = "fake-chat"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, messages, *, max_tokens=512):
        self.prompts.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return ChatResponse(self.reply, Usage("fake", "fake", "chat", 10, 5, 0.001))


def test_structured_json_and_conversation_and_document(mem, tmp_path):
    mem.remember_json({"subject": "Parth", "predicate": "salary", "value": "₹32 LPA", "valid_from": "2026-01-01"}, user_id=U)
    mem.remember_json({"name": "Atlas", "owner": "Priya", "stack": ["Rust", "Go"]}, user_id=U)
    assert mem.recall("What is Parth's salary?", user_id=U).answer == "₹32 LPA"
    assert mem.recall("Who is the owner of Atlas?", user_id=U).answer == "Priya"
    mem.remember_conversation([{"role": "user", "content": "I live in Pune.", "timestamp": "2025-12-01"}, {"role": "assistant", "content": "I live in Mars."}], user_id=U, session_id="s1")
    recs = [r for r in mem.list_memories(user_id=U, session_id="s1") if r.scope_level == "session"]
    assert {r.category for r in recs} == {"episodic"} and any(r.source_type == "inferred" for r in recs)
    assert mem.recall("Where do I live?", user_id=U, session_id="s1").answer == "Pune"  # assistant claim extracted no facts
    doc = tmp_path / "notes.txt"
    doc.write_text("\n\n".join(f"Section {i}. " + "filler " * 80 for i in range(8)) + "\n\nThe rollback window for Orion is 15 minutes.")
    r = mem.ingest_document(doc, user_id=U)
    assert len(r.memory_ids) > 2 and len({mem.get(m, user_id=U).source_id for m in r.memory_ids}) == 1
    assert not (tmp_path / "sources").exists()
    assert "15 minutes" in mem.recall("What is the rollback window for Orion?", user_id=U).answer


def test_duplicate_restatement_can_restore_an_earlier_value(mem, clock):
    mem.remember("I live in Pune.", user_id=U)
    mem.remember("I live in Mumbai.", user_id=U)
    again = mem.remember("I live in Pune.", user_id=U)
    assert again.duplicate_of is not None and mem.get(again.memory_ids[0], user_id=U).mention_count == 2
    assert mem.recall("Where do I live?", user_id=U).answer == "Pune"
    assert mem.stats()["memories"] == 2 and mem.stats()["sources"] == 3  # evidence of every assertion is kept


def test_secrets_are_redacted_before_storage(mem):
    r = mem.remember("The password: s3cr3t-value-123 and key sk-abcdefghijklmnopqrstuvwxyz belong to Atlas.", user_id=U)
    assert r.redactions == 2
    stored = mem.get(r.memory_ids[0], user_id=U).original_content
    assert "s3cr3t" not in stored and "sk-abcdef" not in stored and "[REDACTED" in stored
    assert "s3cr3t" not in str(mem.db.query("SELECT * FROM sources")[0]["content"])


def test_validation_errors(mem):
    for bad in ({"text": " "}, {"text": "x", "source_type": "bogus"}, {"text": "x", "reliability": 2}, {"text": "x", "level": "agent"}):
        with pytest.raises(ValueError):
            mem.remember(user_id=U, **bad)
    with pytest.raises(NotFoundError):
        mem.get("mem_none", user_id=U)
    with pytest.raises(ValueError):
        mem.recall(" ", user_id=U)


def test_verification_changes_reliability_and_resolves_conflicts(mem):
    a = mem.remember("The database of Atlas is PostgreSQL.", user_id=U, source_type="document").memory_ids[0]
    mem.remember("The database of Atlas is MySQL.", user_id=U, source_type="document")
    assert mem.recall("Which database does Atlas use?", user_id=U).status == "conflict"
    mem.verify(a, "verified", user_id=U)
    res = mem.recall("Which database does Atlas use?", user_id=U)
    assert res.status == "answered" and "PostgreSQL" in res.answer
    mem.verify(a, "disputed", user_id=U)
    assert "MySQL" in mem.recall("Which database does Atlas use?", user_id=U).answer
    with pytest.raises(ValueError):
        mem.verify(a, "maybe", user_id=U)


def test_query_cache_is_invalidated_by_writes(mem):
    mem.remember("Parth's salary is ₹28 LPA.", user_id=U)
    first = mem.recall("What is Parth's salary?", user_id=U)
    second = mem.recall("What is Parth's salary?", user_id=U)
    assert not first.cached and second.cached and second.recall_id != first.recall_id
    mem.remember("Parth's salary is ₹30 LPA.", user_id=U)
    third = mem.recall("What is Parth's salary?", user_id=U)
    assert not third.cached and third.answer == "₹30 LPA"
    assert mem.stats()["query_cache"]["hits"] == 1


def test_synthesis_is_verified_against_evidence(mem):
    mem.chat = mem.recaller.chat = FakeChat("Parth earns ₹32 LPA.")
    mem.remember("Parth's salary is ₹32 LPA.", user_id=U)
    ok = mem.recall("What is Parth's salary?", user_id=U, synthesize=True)
    assert ok.answer == "Parth earns ₹32 LPA." and "untrusted" in mem.chat.prompts[0][1]["content"]
    mem.chat.reply = "Parth earns ₹99 LPA."  # hallucinated number is rejected
    assert mem.recall("What is Parth's salary?", user_id=U, synthesize=True, use_cache=False).answer == "₹32 LPA"
    mem.chat.reply = ProviderUnavailable("down")  # provider outage degrades to the extractive answer
    assert mem.recall("What is Parth's salary?", user_id=U, synthesize=True, use_cache=False).answer == "₹32 LPA"
    mem.chat.reply = "INSUFFICIENT"
    assert mem.recall("What is Parth's salary?", user_id=U, synthesize=True, use_cache=False).answer == "₹32 LPA"


def test_episodic_time_windows_and_anchored_before(mem, clock):
    mem.remember("We shipped Project Atlas version one.", user_id=U, source_type="conversation", effective_at="2024-03-01")
    mem.remember("We started the Project Atlas rewrite.", user_id=U, source_type="conversation", effective_at="2024-09-01")
    mem.remember("The Project Atlas launch failed badly.", user_id=U, source_type="conversation", effective_at="2024-12-01")
    mem.remember("We celebrated at the office party.", user_id=U, source_type="conversation", effective_at="2024-12-20")
    res = mem.recall("What happened before the Atlas launch failed?", user_id=U)
    assert res.strategy == "episodic" and res.status == "answered"
    assert [e.excerpt for e in res.evidence][:3] == ["The Project Atlas launch failed badly.", "We started the Project Atlas rewrite.", "We shipped Project Atlas version one."]
    assert "party" not in res.answer
    windowed = mem.recall("What happened with Project Atlas in 2024-09?", user_id=U)
    assert windowed.status == "answered" and "rewrite" in windowed.answer and "shipped" not in windowed.answer


def test_reflect_and_stats_and_health(mem):
    for i in range(3):
        mem.remember(f"Azure architecture note {i}: hub and spoke.", user_id=U)
    mem.remember("The database of Atlas is PostgreSQL.", user_id=U, source_type="document")
    mem.remember("The database of Atlas is MySQL.", user_id=U, source_type="document")
    rep = mem.reflect(user_id=U)
    assert rep["open_conflicts"] and any(e["entity"] == "Azure" for e in rep["recurring_entities"])
    assert mem.reflect(user_id=U, topic="azure")["memories_considered"] == 3
    st = mem.stats()
    assert st["memories"] == 5 and st["facts"] == 2 and st["schema_version"] == 1 and st["embedder"] == "hashing-v1"
    assert mem.health()["audit_chain_valid"]


def test_forget_everything_for_a_user(mem):
    for i in range(3):
        mem.remember(f"Fact number {i} about zebra.", user_id="gone")
    mem.remember("Fact about giraffes.", user_id="stay")
    assert mem.forget(user_id="gone", everything=True) == 3
    assert mem.export(user_id="gone")["memories"] == [] and len(mem.export(user_id="stay")["memories"]) == 1


def test_evaluate_api_reports_metrics(mem):
    r = mem.remember("Parth's salary is ₹32 LPA.", user_id=U)
    cases = [
        {"question": "What is Parth's salary?", "answer": "₹32 LPA", "relevant_memory_ids": r.memory_ids, "category": "exact"},
        {"question": "What is Parth's blood group?", "answerable": False, "category": "unsupported"},
    ]
    rep = mem.evaluate(cases, user_id=U)
    assert rep["summary"]["exact_match_accuracy"] == 1.0 and rep["summary"]["recall_at_k"] == 1.0 and rep["summary"]["unsupported_answer_rate"] == 0.0
    assert set(rep["by_category"]) == {"exact", "unsupported"}


def test_scheduler_runs_incremental_consolidation(mem):
    for i in range(3):
        mem.remember(f"Azure architecture note {i}: hub and spoke.", user_id=U)
    from memoraos.consolidation import ConsolidationScheduler

    s = ConsolidationScheduler(mem, U, "default", 3600)
    assert s.run_once()["created_memory_ids"] and s.run_once()["created_memory_ids"] == [] and s.runs == 2
    mem.start_scheduler(user_id=U, interval_seconds=3600)
    mem._scheduler.stop()


def test_near_duplicates_are_linked_not_deleted(mem):
    a = mem.remember("The weekly platform review covers Azure cost management and governance topics.", user_id=U).memory_ids[0]
    b = mem.remember("The weekly platform review covers Azure cost management and governance topics today.", user_id=U).memory_ids[0]
    rep = mem.consolidate(user_id=U)
    assert rep["near_duplicates"] == [{"duplicate": b, "canonical": a}]
    assert mem.get(b, user_id=U).duplicate_of == a and mem.get(a, user_id=U)
    res = mem.recall("What does the weekly platform review cover?", user_id=U)
    assert [e.memory_id for e in res.evidence] == [a]  # collapsed onto the canonical memory
    mem.rollback_consolidation(rep["run_id"], user_id=U)
    assert mem.get(b, user_id=U).duplicate_of is None


def test_alias_merge_is_conservative(mem):
    mem.remember("Parth Pandya leads Project Atlas.", user_id=U)
    mem.remember("Parth reviewed the roadmap.", user_id=U)
    mem.remember("Azure Functions powers Atlas.", user_id=U)
    mem.remember("Azure Functions and Azure were discussed together.", user_id=U)
    rep = mem.consolidate(user_id=U)
    assert [m["alias"] for m in rep["alias_merges"]] == ["parth"]
    assert any(c["alias"] == "azure" for c in rep["alias_candidates"])  # co-mentioned: proposed, not merged
    g = mem.graph(user_id=U)
    assert {n["id"] for n in g["nodes"]} >= {"parth pandya"} and "parth" not in {n["id"] for n in g["nodes"]}
