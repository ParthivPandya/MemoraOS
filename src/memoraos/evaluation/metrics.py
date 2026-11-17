"""Retrieval and answer metrics. Pure functions; no I/O."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    top = ranked[:k]
    return len([r for r in top if r in relevant]) / len(top) if top else 0.0


def mrr(ranked: Sequence[str], relevant: set[str]) -> float:
    for i, r in enumerate(ranked, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(ranked[:k], start=1) if r in relevant)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def answer_correct(answer: str, gold: str, wrong_values: Sequence[str] = ()) -> bool:
    """Exact-match accuracy as containment: the gold value must appear and no known-wrong value may."""
    a = _norm(answer)
    if _norm(gold) not in a:
        return False
    return not any(_norm(w) in a for w in wrong_values if _norm(w) and _norm(w) not in _norm(gold))


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def percentile(xs: Sequence[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))]
