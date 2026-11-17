"""Feedback-driven strategy learning with an accuracy guard.

Rewards come from explicit feedback (``correct`` true/false) joined to the retrieval log. A learned
override is applied only when ALL of these hold:
  * learning is enabled in settings (off by default)
  * both the default and the candidate strategy have at least ``min_samples`` labelled outcomes
    for the query category
  * the candidate's Wilson *lower* confidence bound for accuracy is >= the default's *point*
    accuracy (so noise cannot dethrone a strategy), and
  * the candidate's accuracy is never below the default's accuracy.
Cost and latency only break ties between strategies that are statistically as accurate; they never
trade accuracy away.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..storage.db import Database

Z95 = 1.96


def wilson_bounds(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


@dataclass
class StrategyStat:
    category: str
    strategy: str
    n: int
    correct: int
    mean_latency_ms: float
    mean_tokens: float

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def strategy_stats(db: Database, tenant_id: str) -> list[StrategyStat]:
    rows = db.query(
        "SELECT r.category AS category, r.strategy AS strategy, COUNT(*) AS n, SUM(f.correct) AS correct,"
        " AVG(r.latency_ms) AS lat, AVG(r.context_tokens) AS tok"
        " FROM retrieval_log r JOIN feedback f ON f.recall_id = r.id AND f.correct IS NOT NULL"
        " WHERE r.tenant_id=? GROUP BY r.category, r.strategy",
        (tenant_id,),
    )
    return [StrategyStat(r["category"], r["strategy"], r["n"], int(r["correct"] or 0), r["lat"] or 0.0, r["tok"] or 0.0) for r in rows]


def make_policy(db: Database, tenant_id: str, min_samples: int):
    """Return a callable (category, default_strategy) -> better strategy or None."""

    def policy(category: str, default: str) -> str | None:
        stats = {s.strategy: s for s in strategy_stats(db, tenant_id) if s.category == category}
        base = stats.get(default)
        if not base or base.n < min_samples:
            return None
        candidates = []
        for name, s in stats.items():
            if name == default or s.n < min_samples:
                continue
            lower, _ = wilson_bounds(s.correct, s.n)
            if lower >= base.accuracy and s.accuracy >= base.accuracy:
                candidates.append((s.accuracy, -s.mean_tokens, -s.mean_latency_ms, name))
        return max(candidates)[3] if candidates else None

    return policy
