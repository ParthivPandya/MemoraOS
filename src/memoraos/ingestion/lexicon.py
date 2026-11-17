"""Predicate vocabulary shared by ingestion (what to call a fact) and retrieval (what a question asks)."""

from __future__ import annotations

import re

from ..util import stem, tokenize

# canonical predicate -> words that, when present in a question, ask about it.
PREDICATE_SYNONYMS: dict[str, set[str]] = {
    "salary": {"salary", "pay", "compensation", "ctc", "income", "earning", "earn", "wage", "package", "lpa"},
    "works_at": {"work", "employer", "company", "job", "employ", "employed", "join", "joined", "employee"},
    "lives_in": {"live", "reside", "city", "location", "based", "home", "relocate", "move", "moved"},
    "uses": {"use", "using", "used", "stack", "tool", "technology", "adopt", "adopted"},
    "prefers": {"prefer", "favorite", "favourite", "like", "love", "favor"},
    "building": {"build", "building", "develop", "developing", "creating", "working"},
    "leads": {"lead", "leads", "led", "manage", "manages", "head", "manager", "owner", "own", "maintain", "maintainer"},
    "depends_on": {"depend", "dependency", "require", "rely"},
    "hosted_in": {"host", "hosted", "deploy", "deployed", "region", "hosting"},
    "reports_to": {"report", "reports", "boss", "supervisor"},
    "part_of": {"part", "belong", "component"},
    "connected_to": {"integrate", "connect", "integration"},
}

# Predicates holding one value at a time (new value supersedes old). "uses" is multi-valued
# except for versioned objects (see ``slot_for``).
SINGLE_VALUED = {
    "salary", "works_at", "lives_in", "title", "role", "email", "phone", "age", "status", "database",
    "version", "reports_to", "budget", "deadline", "name", "owner", "location", "hosted_in",
}
SINGLE_HEADS = {"framework", "database", "version", "salary", "language", "title", "role", "status", "owner", "lead", "manager", "location", "city", "budget", "deadline", "email", "phone", "region", "provider", "editor", "stack", "os"}

RELATIONAL_PREDICATES = {"works_at", "uses", "depends_on", "leads", "part_of", "hosted_in", "reports_to", "connected_to", "building", "lives_in"}
# Nouns that name an attribute of something ("the budget is ...") as opposed to a verb relation.
ATTRIBUTE_HEADS = SINGLE_HEADS | {"price", "cost", "revenue", "fee", "bonus"}

# Predicates produced by the verb patterns in ingestion.extract (as opposed to named attributes like "database").
VERB_PREDICATES = RELATIONAL_PREDICATES | {"prefers"}

_VERSIONED = re.compile(r"^(?P<base>[A-Za-z][A-Za-z.#+\-]*?)[\s\-]*v?(?P<ver>\d+(?:\.\d+)*)$")


def version_parts(value: str) -> tuple[str, str] | None:
    m = _VERSIONED.match(value.strip())
    if not m:
        return None
    return m.group("base").lower().strip(" -"), m.group("ver")


def slot_for(predicate: str, obj: str) -> str | None:
    """Key under which values replace one another, or None when values can co-exist."""
    head = predicate.split()[-1] if predicate else predicate
    if predicate in SINGLE_VALUED or head in SINGLE_HEADS:
        return predicate
    if predicate in {"uses", "depends_on"}:
        vp = version_parts(obj)
        if vp:
            return f"{predicate}:{vp[0]}"
    return None


def predicate_tokens(predicate: str) -> list[str]:
    return [stem(t) for t in re.split(r"[_\s]+", predicate) if t]


def predicate_score(query_stems: set[str], predicate: str) -> float:
    """How strongly a question refers to this predicate (0..1)."""
    base = predicate.split(":")[0]
    best = 0.0
    syn = PREDICATE_SYNONYMS.get(base)
    if syn and query_stems & {stem(s) for s in syn}:
        best = 1.0
    toks = predicate_tokens(base)
    if toks:
        hit = sum(1 for t in toks if t in query_stems)
        if hit:
            head_hit = toks[-1] in query_stems
            best = max(best, hit / len(toks) if head_hit or hit == len(toks) else 0.0)
        # a free-form predicate word that belongs to a synonym group ("owner" ~ "owns") matches the whole group
        if best < 1.0 and len(toks) == 1:
            for words in PREDICATE_SYNONYMS.values():
                group = {stem(w) for w in words}
                if toks[0] in group and query_stems & group:
                    best = 1.0
                    break
    return best


def query_stems(query: str) -> set[str]:
    return {stem(t) for t in tokenize(query)}
