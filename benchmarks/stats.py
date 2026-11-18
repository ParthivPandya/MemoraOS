"""Small, dependency-free statistics for benchmark reports."""

from __future__ import annotations

import math


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default).

    Preferred over a percentile bootstrap for small binary sets: it never degenerates to [100%, 100%] or [0%, 0%]
    for a finite n, which is the honest statement ("we saw 21 of 21, the true rate may still be about 85%")."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def brier(probs: list[float], outcomes: list[bool]) -> float | None:
    if not probs:
        return None
    return sum((p - float(o)) ** 2 for p, o in zip(probs, outcomes, strict=True)) / len(probs)


def ece(probs: list[float], outcomes: list[bool], bins: int = 5) -> float | None:
    """Expected calibration error with equal-width bins. With few samples this is noisy; report n alongside it."""
    if not probs:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if idx:
            conf = sum(probs[i] for i in idx) / len(idx)
            acc = sum(outcomes[i] for i in idx) / len(idx)
            total += len(idx) / len(probs) * abs(conf - acc)
    return total


def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])
