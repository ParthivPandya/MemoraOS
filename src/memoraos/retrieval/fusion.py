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
    out = [Candidate(mid, s, strategy, {"ranks": detail[mid], "ceiling": sum((weights or {}).get(n, 1.0) for n in detail[mid]) / (k + 1)}) for mid, s in fused.items()]
    out.sort(key=lambda c: (-c.score, order[c.memory_id]))
    return out


STRATEGIES = ("rrf", "weighted_rrf", "linear")


def linear(rankings: dict[str, list[Candidate]], weights: dict[str, float] | None = None, strategy: str = "hybrid") -> list[Candidate]:
    """Weighted sum of per-list min-max normalised scores. More sensitive to score scale than RRF, so it is opt-in."""
    fused: dict[str, float] = {}
    detail: dict[str, dict[str, int]] = {}
    order: dict[str, int] = {}
    for name, cands in rankings.items():
        if not cands:
            continue
        w = (weights or {}).get(name, 1.0)
        hi, lo = max(c.score for c in cands), min(c.score for c in cands)
        span = hi - lo
        for rank, c in enumerate(cands, start=1):
            norm = 1.0 if span <= 1e-12 else (c.score - lo) / span
            fused[c.memory_id] = fused.get(c.memory_id, 0.0) + w * norm
            detail.setdefault(c.memory_id, {})[name] = rank
            order.setdefault(c.memory_id, len(order))
    out = [Candidate(mid, s, strategy, {"ranks": detail[mid], "ceiling": sum((weights or {}).get(n, 1.0) for n in detail[mid])}) for mid, s in fused.items()]
    out.sort(key=lambda c: (-c.score, order[c.memory_id]))
    return out


def fuse(
    rankings: dict[str, list[Candidate]], *, strategy: str = "rrf", weights: dict[str, float] | None = None, k: int = 60,
    result_strategy: str = "hybrid",
) -> list[Candidate]:
    rankings = {n: c for n, c in rankings.items() if c}
    if strategy == "rrf":
        return rrf(rankings, k, weights, result_strategy)
    if strategy == "weighted_rrf":
        return rrf(rankings, k, weights, result_strategy)
    if strategy == "linear":
        return linear(rankings, weights, result_strategy)
    raise ValueError(f"unknown fusion strategy '{strategy}' (expected one of {STRATEGIES})")
