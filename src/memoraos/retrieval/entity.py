"""Entity and exact-identifier retrievers.

Dense and BM25 retrieval blur things that must match exactly: project names, ticket numbers, versions, amounts.
These two retrievers add precision for them. Both are deterministic and read only the SQLite index.
"""

from __future__ import annotations

import re

from ..extraction.values import parse_value
from ..ingestion.extract import norm_entity
from ..models import Scope
from ..storage.db import Database
from ..storage.visibility import visibility_clause
from ..util import STOPWORDS, stem, tokenize
from .lexical import Candidate

_CAP = re.compile(r"\b[A-Z][\w.#+\-]*(?:\s+[A-Z][\w.#+\-]*)*")
_IDENT = re.compile(
    r"\b[A-Za-z]{1,10}[-_#]\d[\w\-]*\b"  # INV-1234, JIRA-77, ticket#12
    r"|\bv?\d+(?:\.\d+){1,3}\b"  # 2.3.1, v1.2
    r"|\b[\w.+-]+@[\w-]+\.[\w.-]+\b"  # emails
    r"|\b\d{3,}\b"  # long numbers
    r'|"([^"]{2,60})"',  # quoted strings
)
_MONEY = re.compile(r"(?:₹|\$|€|£|rs\.?\s*)?\d[\d,]*(?:\.\d+)?\s*(?:lakhs?|lacs?|lpa|crores?|k|m|million|billion)?(?:\s+(?:per\s+annum|annually|a\s+year|per\s+year|per\s+month|monthly))?", re.I)


def query_entities(query: str) -> list[str]:
    """Capitalised names in the question, minus a leading question word."""
    out = []
    for m in _CAP.finditer(query):
        words = m.group(0).split()
        while words and words[0].lower() in STOPWORDS:
            words = words[1:]
        name = " ".join(words)
        if name and name.lower() not in STOPWORDS:
            out.append(name)
    return list(dict.fromkeys(out))


def exact_identifiers(query: str) -> list[str]:
    found = []
    for m in _IDENT.finditer(query):
        found.append(m.group(1) or m.group(0))
    return list(dict.fromkeys(found))


def _phrase(ident: str) -> str | None:
    toks = re.findall(r"\w+", ident)
    return '"' + " ".join(toks) + '"' if toks else None


def entity_search(db: Database, scope: Scope, query: str, k: int) -> list[Candidate]:
    """Memories mentioning the entities named in the question, rarer entities weighing more."""
    names = query_entities(query)
    keys = list(dict.fromkeys(norm_entity(n) for n in names))
    # also try single words of multi-word names, so "Atlas" matches a memory that mentions "Project Atlas"
    for n in names:
        keys.extend(k2 for k2 in (norm_entity(w) for w in n.split()) if k2 and k2 not in STOPWORDS)
    keys = [k2 for k2 in dict.fromkeys(keys) if k2 and k2 != "user"]
    if not keys:
        return []
    vis, params = visibility_clause(scope, "m")
    marks = ",".join("?" * len(keys))
    rows = db.query(
        f"SELECT m.id AS id, mn.entity_key AS ek FROM mentions mn JOIN memories m ON m.id = mn.memory_id"
        f" WHERE mn.entity_key IN ({marks}) AND m.status='active' AND {vis} ORDER BY m.rowid",
        [*keys, *params],
    )
    if not rows:
        return []
    df: dict[str, int] = {}
    per: dict[str, set[str]] = {}
    for r in rows:
        per.setdefault(r["id"], set()).add(r["ek"])
        df[r["ek"]] = df.get(r["ek"], 0) + 1
    scored = [(sum(1.0 / (1 + df[e]) + 1.0 for e in ents), mid) for mid, ents in per.items()]
    scored.sort(key=lambda x: -x[0])
    return [Candidate(mid, s, "entity") for s, mid in scored[:k]]


def exact_search(db: Database, scope: Scope, query: str, k: int) -> list[Candidate]:
    """Memories containing an identifier, version, number, quoted string, or an equal monetary value."""
    idents = exact_identifiers(query)
    vis, params = visibility_clause(scope, "m")
    scores: dict[str, float] = {}
    phrases = [p for p in (_phrase(i) for i in idents) if p]
    if phrases:
        rows = db.query(
            "SELECT m.id AS id, bm25(memories_fts) AS rank FROM memories_fts JOIN memories m ON m.rowid = memories_fts.rowid"
            f" WHERE memories_fts MATCH ? AND m.status='active' AND {vis} ORDER BY rank LIMIT ?",
            [" OR ".join(phrases), *params, k],
        )
        for r in rows:
            scores[r["id"]] = scores.get(r["id"], 0.0) + 1.0 - float(r["rank"]) * 0.001
    # a monetary amount in the question finds facts whose canonical value is equal, whatever the wording
    keys = {pv.key for m in _MONEY.finditer(query) if (pv := parse_value(m.group(0).strip(), "budget", query)) is not None}
    keys |= {pv.key for m in _MONEY.finditer(query) if (pv := parse_value(m.group(0).strip(), "salary", query)) is not None}
    if keys:
        marks = ",".join("?" * len(keys))
        fvis, fparams = visibility_clause(scope, "f")
        rows = db.query(
            f"SELECT DISTINCT f.memory_id AS id FROM facts f JOIN memories m ON m.id=f.memory_id WHERE f.object_key IN ({marks})"
            f" AND f.retracted_at IS NULL AND f.polarity='affirmed' AND m.status='active' AND {fvis} LIMIT ?",
            [*keys, *fparams, k],
        )
        for r in rows:
            scores[r["id"]] = scores.get(r["id"], 0.0) + 1.0
    return [Candidate(mid, s, "exact") for mid, s in sorted(scores.items(), key=lambda x: -x[1])[:k]]


def informative_terms(query: str) -> set[str]:
    return {stem(t) for t in tokenize(query) if t not in STOPWORDS}
