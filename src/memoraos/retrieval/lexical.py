"""Lexical retrieval: SQLite FTS5 (BM25) for live data, an in-memory BM25 for historical snapshots."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from ..models import Scope
from ..storage.db import Database
from ..storage.visibility import visibility_clause
from ..util import STOPWORDS, stem, tokenize


@dataclass
class Candidate:
    memory_id: str
    score: float
    strategy: str
    detail: dict | None = None


def fts_match_expression(query: str) -> str | None:
    terms = []
    for t in tokenize(query):
        if t in STOPWORDS or len(t) < 2:
            continue
        terms.append('"' + t.replace('"', '""') + '"')
    terms = list(dict.fromkeys(terms))
    return " OR ".join(terms) if terms else None


def fts_search(db: Database, scope: Scope, query: str, k: int) -> list[Candidate]:
    expr = fts_match_expression(query)
    if not expr:
        return []
    vis, params = visibility_clause(scope, "m")
    rows = db.query(
        "SELECT m.id AS id, bm25(memories_fts) AS rank FROM memories_fts JOIN memories m ON m.rowid = memories_fts.rowid"
        f" WHERE memories_fts MATCH ? AND m.status='active' AND {vis} ORDER BY rank, m.rowid LIMIT ?",
        [expr, *params, k],
    )
    return [Candidate(r["id"], -float(r["rank"]), "bm25") for r in rows]


class PyBM25:
    """Okapi BM25 over a small in-memory corpus (used for as-of snapshots and baselines)."""

    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids = list(docs)
        self.tf: list[Counter[str]] = []
        for d in docs.values():
            self.tf.append(Counter(stem(t) for t in tokenize(d) if t not in STOPWORDS))
        self.lengths = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(self.ids)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int) -> list[Candidate]:
        q = [stem(t) for t in tokenize(query) if t not in STOPWORDS]
        scores: list[tuple[float, int]] = []
        for i, c in enumerate(self.tf):
            s = 0.0
            for t in q:
                f = c.get(t, 0)
                if f:
                    s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg or 1.0)))
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda x: (-x[0], x[1]))
        return [Candidate(self.ids[i], s, "bm25") for s, i in scores[:k]]


_SENT_END = re.compile(r"[.!?]+$")
