"""Run QA cases against a MemoryOS instance and aggregate metrics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .metrics import answer_correct, mean, mrr, ndcg_at_k, percentile, precision_at_k, recall_at_k

if TYPE_CHECKING:
    from ..engine import MemoryOS


def evaluate_memory(engine: MemoryOS, cases: Sequence[dict], *, user_id: str, tenant_id: str = "default", k: int = 5) -> dict:
    """cases: {question, answer?, wrong_values?, relevant_memory_ids?, answerable?, category?, as_of?}"""
    per_case: list[dict] = []
    for c in cases:
        res = engine.recall(c["question"], user_id=user_id, tenant_id=tenant_id, top_k=k, as_of=c.get("as_of"), use_cache=False)
        ranked = [e.memory_id for e in res.evidence]
        rel = set(c.get("relevant_memory_ids") or [])
        answerable = c.get("answerable", True)
        row = {
            "question": c["question"], "category": c.get("category", "all"), "strategy": res.strategy, "status": res.status,
            "answerable": answerable, "latency_ms": res.latency_ms, "context_tokens": res.context_tokens,
        }
        if answerable:
            row["correct"] = res.supported and c.get("answer") is not None and answer_correct(res.answer, c["answer"], c.get("wrong_values", ()))
            if rel:
                row.update(recall=recall_at_k(ranked, rel, k), precision=precision_at_k(ranked, rel, k), mrr=mrr(ranked, rel), ndcg=ndcg_at_k(ranked, rel, k), evidence_hit=float(bool(set(ranked) & rel)))
            row["false_abstain"] = not res.supported
        else:
            row["unsupported_answer"] = res.status != "insufficient_evidence"
        per_case.append(row)
    return {"summary": summarize(per_case), "by_category": {cat: summarize([r for r in per_case if r["category"] == cat]) for cat in sorted({r["category"] for r in per_case})}, "cases": per_case}


def summarize(rows: Sequence[dict]) -> dict:
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    out: dict = {"n": len(rows), "n_answerable": len(ans), "n_unanswerable": len(unans)}
    if ans:
        out["exact_match_accuracy"] = mean([float(r["correct"]) for r in ans])
        out["false_abstain_rate"] = mean([float(r["false_abstain"]) for r in ans])
        for key, name in (("recall", "recall_at_k"), ("precision", "precision_at_k"), ("mrr", "mrr"), ("ndcg", "ndcg_at_k"), ("evidence_hit", "evidence_coverage")):
            vals = [r[key] for r in ans if key in r]
            if vals:
                out[name] = mean(vals)
    if unans:
        out["unsupported_answer_rate"] = mean([float(r["unsupported_answer"]) for r in unans])
    out["mean_context_tokens"] = mean([r["context_tokens"] for r in rows])
    out["latency_ms_p50"] = percentile([r["latency_ms"] for r in rows], 0.5)
    out["latency_ms_p95"] = percentile([r["latency_ms"] for r in rows], 0.95)
    strat: dict[str, int] = defaultdict(int)
    for r in rows:
        strat[r["strategy"]] += 1
    out["strategy_usage"] = dict(strat)
    return out
