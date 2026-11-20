"""Regressions found by running the real-document benchmark (benchmarks/real_docs.py) on MemoraOS's own docs."""

from __future__ import annotations

from benchmarks import real_docs
from memoraos.routing.router import RouterHints, analyze_query, category_scores

U = "user_001"

SECTION = (
    "## Security notes\n\n"
    "Encryption at rest is not implemented in code. The REST API binds to 127.0.0.1 by default. "
    "API keys are stored only as SHA-256 hashes and are never logged."
)


def test_one_negated_sentence_does_not_hide_the_rest_of_a_section(mem):
    mem.remember(SECTION, user_id=U, source_type="document")
    r = mem.recall("Which address does the API bind to by default?", user_id=U, use_cache=False)
    assert r.status == "answered" and "127.0.0.1" in r.answer
    assert "not implemented" not in r.answer  # the negated sentence itself is still withheld from positive answers


def test_a_negated_sentence_is_still_never_quoted_as_a_positive_answer(mem):
    mem.remember("Alice does not manage Project Atlas. The review is on Friday.", user_id=U, source_type="document")
    r = mem.recall("Who does Alice manage?", user_id=U, use_cache=False)
    assert "does not manage" not in r.answer


def test_an_answer_can_span_two_sentences_of_one_memory(mem):
    mem.remember("API keys are never logged. They are stored only as SHA-256 hashes.", user_id=U, source_type="document")
    q = "How are API keys stored and logged?"
    r = mem.recall(q, user_id=U, use_cache=False)
    assert r.status == "answered" and "never logged" in r.answer and "SHA-256" in r.answer
    mem.settings.answer_max_sentences = 1  # v0.1 behaviour: only the best sentence
    one = mem.recall(q, user_id=U, use_cache=False)
    assert not ("never logged" in one.answer and "SHA-256" in one.answer)


def test_the_attribute_word_guard_yields_to_strong_term_coverage(mem):
    mem.remember("The API keys are stored as SHA-256 hashes, never as plain text.", user_id=U, source_type="document")
    q = "How are the API keys stored on disk?"  # 'disk' never occurs in the evidence
    assert mem.recall(q, user_id=U, use_cache=False).status == "answered"
    mem.settings.head_guard_coverage = 1.01  # v0.1 behaviour
    assert mem.recall(q, user_id=U, use_cache=False).status == "insufficient_evidence"


def test_the_guard_still_refuses_when_the_attribute_is_really_missing(mem):
    mem.remember("Parth lives in Pune.", user_id=U)
    assert mem.recall("What is Parth's blood group?", user_id=U, use_cache=False).status == "insufficient_evidence"


def test_extra_sentences_extend_an_answer_but_never_create_its_support(mem):
    # no single sentence supports the question; adding sentences up must not make it "answered"
    mem.remember("The REST API and a Python client were added. Defaults are described elsewhere. Network binding is not covered here.", user_id=U, source_type="document")
    q = "Which address does the REST API bind to by default?"
    assert mem.recall(q, user_id=U, use_cache=False).status == "insufficient_evidence"


def test_chunks_never_start_in_the_middle_of_a_line():
    from memoraos.ingestion.classify import chunk_text

    rows = [f"| Control {i} | Implementation detail number {i} with some descriptive words attached to it | tests |" for i in range(40)]
    text = "| Control | Implementation | Tests |\n|---|---|---|\n" + "\n".join(rows)
    chunks = chunk_text(text, 400, 120)
    assert len(chunks) > 3
    lines = set(text.splitlines())
    for c in chunks:
        assert c.splitlines()[0] in lines, c[:60]


def test_bare_before_in_a_prose_question_is_not_a_time_question():
    q = "What placeholder replaces a detected secret before it is stored?"
    cats = category_scores(analyze_query(q), RouterHints())
    assert cats["temporal"] < cats["semantic"]
    assert category_scores(analyze_query("What happened before the migration failed?"), RouterHints())["episodic"] > 0.4
    assert category_scores(analyze_query("What was the salary before 2025?"), RouterHints())["temporal"] >= 0.5


def test_two_capitalised_names_alone_do_not_select_the_graph_strategy():
    cats = category_scores(analyze_query("How much GPU memory does the Memorilla README call for?"), RouterHints(graph_entities=2))
    assert cats["multi_hop"] < 0.3
    assert category_scores(analyze_query("How is Alice related to Azure Functions?"), RouterHints(graph_entities=2))["multi_hop"] >= 0.5


def test_real_document_benchmark_integrity_holds():
    """Every gold answer is in the corpus and every 'unanswerable' term is absent from it (build() aborts otherwise)."""
    sc, origin, sha = real_docs.build()
    assert len(sha) == 64 and sc.events and len(origin) == len(sc.events)
    answerable = [q for q in sc.questions if q.answerable]
    assert len(answerable) == len(real_docs.ANSWERABLE) + len(real_docs.HELDOUT_ANSWERABLE)
    assert all(q.relevant for q in answerable)
    assert not any(e.text.startswith("# Real-document benchmark") for e in sc.events)  # reports are not part of the corpus


def _load_releases(mem):
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).resolve().parents[2] / "data" / "python_releases.json").read_text(encoding="utf-8"))
    for rec in data["records"]:
        mem.remember_json({k: rec[k] for k in ("subject", "predicate", "object", "valid_from")}, user_id=U, origin=rec["source"])


def test_a_version_the_facts_never_mention_is_not_answered_by_the_unversioned_subject(mem):
    # found by benchmarks/real_temporal.py: "Python 3.15" was answered with the latest *stable* version of "Python"
    _load_releases(mem)
    assert mem.recall("What is the latest version of Python 3.15?", user_id=U, use_cache=False).status == "insufficient_evidence"
    assert mem.recall("What is the latest stable version of Python?", user_id=U, use_cache=False).answer == "3.14"
    assert mem.recall("What was the latest version of Python 3.14 on 2025-11-01?", user_id=U, use_cache=False).answer.startswith("3.14.0")


def test_a_passage_without_the_version_named_in_the_question_is_not_an_answer(mem):
    mem.remember("As of 2025-10-07, the latest version of Python 3.14 is 3.14.0.", user_id=U, source_type="document")
    q = "What was the latest version of Python 3.11 on 2023-01-01?"
    assert mem.recall(q, user_id=U, use_cache=False).status == "insufficient_evidence"
    assert mem.recall("What was the latest version of Python 3.14?", user_id=U, use_cache=False).status == "answered"


def test_a_plan_is_one_value_at_a_time(mem):
    # found while writing a Memory CI contract: "current plan" returned both the old and the new plan
    mem.remember("The plan of Acme is Professional.", user_id=U, effective_at="2024-03-01T00:00:00Z")
    mem.remember("The plan of Acme is Enterprise.", user_id=U, effective_at="2025-06-01T00:00:00Z")
    assert mem.recall("What is the current plan of Acme?", user_id=U, use_cache=False).answer == "Enterprise"
    assert mem.recall("What was the plan of Acme in 2024?", user_id=U, use_cache=False).answer.startswith("Professional")


def test_a_later_near_identical_statement_beats_an_earlier_one_without_extracted_facts(mem):
    mem.remember("The customer plan is Basic.", user_id=U, effective_at="2024-01-01")
    mem.remember("The customer plan is Premium.", user_id=U, effective_at="2024-06-01")
    r = mem.recall("What is the customer plan?", user_id=U, use_cache=False)
    assert "Premium" in r.answer and "Basic" not in r.answer


def test_the_older_of_two_passage_variants_is_flagged(mem):
    mem.remember("Acme billing review: the customer tier is Basic.", user_id=U, effective_at="2024-01-01")
    mem.remember("Acme billing review: the customer tier is Premium.", user_id=U, effective_at="2024-06-01")
    r = mem.recall("What is the customer tier?", user_id=U, use_cache=False)
    assert "Premium" in r.answer and "Basic" not in r.answer
    assert any("older_variant" in e.flags for e in r.evidence)


def test_recency_preference_is_order_independent_and_skipped_for_timed_questions(mem):
    mem.remember("The customer plan is Premium.", user_id=U, effective_at="2024-06-01")
    mem.remember("The customer plan is Basic.", user_id=U, effective_at="2024-01-01")
    assert "Premium" in mem.recall("What is the customer plan?", user_id=U, use_cache=False).answer
    r = mem.recall("What was the customer plan in January 2024?", user_id=U, use_cache=False)
    assert "Basic" in r.answer


def test_different_subjects_with_similar_wording_are_not_treated_as_updates(mem):
    mem.remember("Python 3.11 reaches end of life in 2027.", user_id=U, effective_at="2024-01-01")
    mem.remember("Python 3.12 reaches end of life in 2028.", user_id=U, effective_at="2024-06-01")
    r = mem.recall("When does Python 3.11 reach end of life?", user_id=U, use_cache=False)
    assert "2027" in r.answer


def test_verb_forms_with_silent_e_share_a_stem_and_recall_answers(mem):
    from memoraos.util import stem

    assert len({stem(w) for w in ("rotate", "rotates", "rotating", "rotated")}) == 1
    assert stem("release") == stem("releases")
    mem.remember("The deploy key rotates every 90 days", user_id=U)
    r = mem.recall("how often does the deploy key rotate", user_id=U, use_cache=False)
    assert r.status == "answered" and "90 days" in r.answer
