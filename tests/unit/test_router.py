import json

import pytest

from memoraos.config import Settings
from memoraos.routing import AdaptiveRouter, RouterHints, analyze_query, wilson_bounds
from memoraos.routing.learning import make_policy
from memoraos.routing.router import STRATEGY_COST


@pytest.fixture
def router():
    return AdaptiveRouter(Settings())


def test_features():
    f = analyze_query("What was my salary in 2025 and how did it change?")
    assert f.temporal_cue and f.personal and f.time_ref and f.time_ref.start == "2025-01-01"
    assert analyze_query("Find error E4021").code_like
    assert analyze_query("Summarize everything about AI").summary_cue
    assert "year" not in analyze_query("over the last three years what did I build").terms


def test_categories(router):
    hints = RouterHints(slot_match=True)
    assert router.route("What is my exact current salary?", hints).category == "exact_fact"
    assert router.route("What was my salary in 2025?", hints).category == "temporal"
    assert router.route("How is Alice related to Azure?", RouterHints(graph_entities=2)).category == "multi_hop"
    assert router.route("How do I deploy the service?").category == "procedural"
    assert router.route("Summarize everything about AI memory").category == "summarization"
    assert router.route("tell me something nice").category == "semantic"


def test_exact_is_not_selected_without_a_matching_fact(router):
    plan = router.route("What is the capital of France?", RouterHints(slot_match=False))
    assert plan.primary != "exact" and plan.scores["exact"] == 0.0


def test_plans_always_include_fallbacks_and_are_explainable(router):
    plan = router.route("What is my salary?", RouterHints(slot_match=True))
    assert plan.stages[0] == plan.primary and "hybrid" in plan.fallbacks and plan.reasons and plan.estimated_cost == STRATEGY_COST[plan.primary]
    assert plan.route_confidence > 0


def test_cost_awareness_prefers_cheaper_strategy_within_tolerance():
    cheap = AdaptiveRouter(Settings(cost_tolerance=0.3)).route("tell me something nice")
    assert cheap.primary in {"vector", "bm25", "hybrid"} and STRATEGY_COST[cheap.primary] <= STRATEGY_COST["hybrid"]


def test_allowed_strategies_are_respected(router):
    plan = router.route("How is Alice related to Azure?", RouterHints(graph_entities=2), allow_strategies={"hybrid", "bm25"})
    assert set(plan.stages) <= {"hybrid", "bm25"}


def test_model_classifier_is_optional_and_validated():
    class Chat:
        name = "fake"

        def __init__(self, text):
            self.text = text

        def complete(self, messages, *, max_tokens=512):
            from memoraos.providers.base import ChatResponse, Usage

            return ChatResponse(self.text, Usage("fake", "fake", "chat"))

    r = AdaptiveRouter(Settings(low_route_confidence=0.9), classifier=Chat(json.dumps({"category": "procedural"})))
    assert r.route("hmm okay").category == "procedural"
    bad = AdaptiveRouter(Settings(low_route_confidence=0.9), classifier=Chat("not json at all"))
    assert bad.route("hmm okay").category == "semantic"
    wrong = AdaptiveRouter(Settings(low_route_confidence=0.9), classifier=Chat('{"category": "made_up"}'))
    assert wrong.route("hmm okay").category == "semantic"


def test_wilson_bounds():
    lo, hi = wilson_bounds(8, 10)
    assert 0.4 < lo < 0.8 < hi < 1.0
    assert wilson_bounds(0, 0) == (0.0, 1.0)


def test_learned_policy_needs_evidence_and_never_trades_accuracy(mem):
    def log(i, strategy, correct):
        rid = f"r{strategy}{i}"
        mem.db.execute(
            "INSERT INTO retrieval_log(id, ts, tenant_id, user_id, query, category, strategy, strategies_tried, fallback_used, status, supported, answer, latency_ms, context_tokens, plan, explanation, evidence_ids)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, "t", "default", "u", "q", "semantic", strategy, "[]", 0, "answered", 1, "", 1.0, 10, "{}", "{}", "[]"),
        )
        mem.db.execute("INSERT INTO feedback(recall_id, ts, correct) VALUES(?,?,?)", (rid, "t", int(correct)))

    policy = make_policy(mem.db, "default", min_samples=20)
    assert policy("semantic", "hybrid") is None  # no data
    for i in range(30):
        log(i, "hybrid", i % 10 != 0)  # 90% accurate default
        log(i, "bm25", i % 2 == 0)  # 50% accurate challenger
    assert policy("semantic", "hybrid") is None  # inferior challenger never wins
    for i in range(60):
        log(100 + i, "vector", True)  # 100% accurate challenger
    assert policy("semantic", "hybrid") == "vector"
    assert make_policy(mem.db, "default", min_samples=100)("semantic", "hybrid") is None


def test_learning_is_disabled_by_default(mem):
    mem.remember("The user is building an AI platform.", user_id="u")
    res = mem.recall("What is the user building?", user_id="u")
    mem.feedback(res.recall_id, correct=True)
    assert not res.plan.learned_override
    assert mem.strategy_report()[0]["n"] == 1
