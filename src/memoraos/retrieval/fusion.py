"""Rank fusion."""

from __future__ import annotations

from .lexical import Candidate


def rrf(rankings: dict[str, list[Candidate]], k: int = 60, weights: dict[str, float] | None = None, strategy: str = "hybrid") -> list[Candidate]:
    """Reciprocal rank fusion: score = sum_i w_i / (k + rank_i). Ties keep first-seen order."""
    fused: dict[str, float] = {}
    detail: dict[str, dict[str, int]] = {}
    order: dict[str, int] = {}
    for name, cands in rankings.items():
        w = (weights or {}).get(name, 1.0)
        for rank, c in enumerate(cands, start=1):
            fused[c.memory_id] = fused.get(c.memory_id, 0.0) + w / (k + rank)
            detail.setdefault(c.memory_id, {})[name] = rank
            order.setdefault(c.memory_id, len(order))
    out = [Candidate(mid, s, strategy, {"ranks": detail[mid]}) for mid, s in fused.items()]
    out.sort(key=lambda c: (-c.score, order[c.memory_id]))
    return out
