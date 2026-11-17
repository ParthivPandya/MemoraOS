"""Fact access and question-to-slot matching (powers exact, temporal and reverse lookups)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extraction.values import parse_value
from ..ingestion.extract import FIRST_PERSON, norm_entity
from ..ingestion.lexicon import VERB_PREDICATES, predicate_score, query_stems, version_parts
from ..models import Fact, Scope
from ..storage.db import Database
from ..storage.visibility import visibility_clause
from ..util import STOPWORDS, stem, tokenize
from .answer_type import detect_answer_type

_FIRST_PERSON_Q = {"i", "my", "me", "we", "our", "mine", "myself"}
PREDICATE_THRESHOLD = 0.5


def load_aliases(db: Database, scope: Scope) -> dict[str, str]:
    vis, params = visibility_clause(scope)
    rows = db.query(f"SELECT alias_key, canonical_key FROM aliases WHERE active=1 AND {vis}", params)
    return {r["alias_key"]: r["canonical_key"] for r in rows}


def _system_filter(as_of: str | None) -> tuple[str, list]:
    if as_of is None:
        return "f.retracted_at IS NULL", []
    return "f.recorded_at <= ? AND (f.retracted_at IS NULL OR f.retracted_at > ?)", [as_of, as_of]


def load_facts(
    db: Database, scope: Scope, *, as_of: str | None = None, predicates: list[str] | None = None,
    subject_keys: list[str] | None = None, object_keys: list[str] | None = None, memory_ids: list[str] | None = None,
    include_negated: bool = False,
) -> list[Fact]:
    """Facts visible to ``scope``.

    Negated facts ("I do not use Angular") never answer a positive question. Unless ``include_negated`` is set they
    are consumed here: a negation recorded later than an affirmed fact about the same subject, predicate and
    value ends that fact's validity, so "I no longer use Angular" really does retire "I use Angular".
    """
    vis, params = visibility_clause(scope, "f")
    sys_sql, sys_params = _system_filter(as_of)
    where = [vis, "m.status='active'", sys_sql]
    args: list = [*params, *sys_params]
    for col, vals in (("f.predicate", predicates), ("f.subject_key", subject_keys), ("f.object_key", object_keys), ("f.memory_id", memory_ids)):
        if vals is not None:
            if not vals:
                return []
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            args += vals
    rows = db.query(
        "SELECT f.*, m.source_id AS source_id, s.source_type AS source_type, s.verification AS verification"
        " FROM facts f JOIN memories m ON m.id = f.memory_id JOIN sources s ON s.id = m.source_id"
        f" WHERE {' AND '.join(where)} ORDER BY f.rowid",
        args,
    )
    facts = [
        Fact(
            id=r["id"], memory_id=r["memory_id"], subject=r["subject"], predicate=r["predicate"], object=r["object"],
            subject_key=r["subject_key"], object_key=_object_key(r), slot=r["slot"], valid_from=r["valid_from"],
            valid_until=r["valid_until"], recorded_at=r["recorded_at"], retracted_at=r["retracted_at"],
            extraction_confidence=r["extraction_confidence"], source_reliability=r["source_reliability"],
            source_id=r["source_id"], source_type=r["source_type"], verification=r["verification"], excerpt=r["excerpt"],
            polarity=r["polarity"], extraction_method=r["extraction_method"],
            span_start=r["source_span_start"], span_end=r["source_span_end"],
        )
        for r in rows
    ]
    if include_negated:
        return facts
    negations = [f for f in facts if f.polarity == "negated"]
    affirmed = [f for f in facts if f.polarity != "negated"]
    for n in negations:
        cutoff = n.valid_from or n.recorded_at
        for a in affirmed:
            if (
                a.recorded_at < n.recorded_at and a.subject_key == n.subject_key and a.predicate == n.predicate
                and a.object_key == n.object_key and (a.valid_until is None or a.valid_until > cutoff)
                and (a.valid_from is None or a.valid_from < cutoff)
            ):
                a.valid_until = cutoff
    return affirmed


def _object_key(r) -> str:
    """Stored key, upgraded on read to the canonical value key so v0.1 rows compare equal to v0.2 rows."""
    if r["value_num"] is None and not r["object_key"].startswith("money:"):
        pv = parse_value(r["object"], r["predicate"], r["excerpt"])
        if pv:
            return pv.key
    return r["object_key"]


def distinct_predicates(db: Database, scope: Scope) -> list[str]:
    vis, params = visibility_clause(scope, "f")
    rows = db.query(f"SELECT DISTINCT f.predicate FROM facts f WHERE f.retracted_at IS NULL AND f.polarity='affirmed' AND {vis}", params)
    return [r[0] for r in rows]


@dataclass
class SlotQuery:
    """The result of mapping a question onto stored facts."""

    facts: list[Fact] = field(default_factory=list)
    predicates: list[str] = field(default_factory=list)
    reverse: bool = False  # question asks for the subject (e.g. "who leads Atlas?")
    assumed_subject: bool = False
    subject_keys: list[str] = field(default_factory=list)
    rejected: str = ""  # why facts were matched but refused (answer-type guard)

    def __bool__(self) -> bool:
        return bool(self.facts)


def _named_entities(query: str) -> list[str]:
    """Capitalised words that are not the first word of the question and not common words."""
    return [
        m.group(0) for m in re.finditer(r"\b[A-Z][\w.#+\-]*", query)
        if m.start() > 0 and m.group(0).lower() not in STOPWORDS and m.group(0) not in {"I", "I'm"}
    ]


def _entity_in_query(key: str, q_stems: set[str], q_text: str) -> bool:
    if not key or key == "user":
        return False
    toks = [stem(t) for t in tokenize(key) if t not in STOPWORDS]
    if not toks:
        return False
    return all(t in q_stems for t in toks) or re.search(rf"\b{re.escape(key)}\b", q_text) is not None


def _unseen_qualifier(subject: str, q_text: str, facts: list[Fact], canon) -> bool:
    """True when the question qualifies the subject with a version ("Python 3.15") that none of the subject's stored
    values mention: the facts are about the unqualified subject, not about that release."""
    m = re.search(rf"\b{re.escape(subject)}\s+v?(\d+(?:\.\d+)+)(?!\w)", q_text)
    if not m or m.group(1) in subject:
        return False
    ver = m.group(1)
    objects = {f.object.strip().lower() for f in facts if canon(f.subject_key) == subject}
    return not any(o == ver or o.startswith(ver + ".") or ver.startswith(o + ".") for o in objects)


def match_slots(db: Database, scope: Scope, query: str, *, as_of: str | None = None) -> SlotQuery:
    q_stems = query_stems(query)
    q_text = query.lower()
    preds = [p for p in distinct_predicates(db, scope) if predicate_score(q_stems, p) >= PREDICATE_THRESHOLD]
    if not preds and re.match(r"^\s*(?:what|who)\s+(?:is|are|was|were)\b", query, re.I):
        preds = ["is"] if "is" in distinct_predicates(db, scope) else []
    if not preds:
        return SlotQuery()
    facts = load_facts(db, scope, as_of=as_of, predicates=preds)
    if not facts:
        return SlotQuery()
    aliases = load_aliases(db, scope)

    def canon(k: str) -> str:
        return aliases.get(k, k)

    first_person = bool(q_stems & _FIRST_PERSON_Q) or bool(re.search(r"\b(?:i|my|me)\b", q_text))
    subjects = {canon(f.subject_key) for f in facts}
    matched = {s for s in subjects if _entity_in_query(s, q_stems, q_text)}
    alias_hits = {canon(a) for a in aliases if _entity_in_query(a, q_stems, q_text)}
    matched |= alias_hits & subjects
    matched = {s for s in matched if not _unseen_qualifier(s, q_text, facts, canon)}
    if first_person and "user" in subjects:
        matched.add("user")
    chosen: list[Fact] = []
    reverse = False
    assumed = False
    if matched:
        chosen = [f for f in facts if canon(f.subject_key) in matched]
    else:
        objects = {canon(f.object_key) for f in facts}
        obj_hits = set()
        for o in objects:
            vp = version_parts(o)
            if _entity_in_query(norm_entity(o), q_stems, q_text) or (vp and _entity_in_query(vp[0], q_stems, q_text)):
                obj_hits.add(o)
        if obj_hits:
            chosen = [f for f in facts if canon(f.object_key) in obj_hits]
            reverse = bool(chosen)
        elif len(subjects) == 1 and not _named_entities(query):
            chosen, assumed = list(facts), True
        elif first_person and not _named_entities(query):
            chosen, assumed = list(facts), True
    if not chosen:
        return SlotQuery()
    # a question naming one predicate strongly should not return unrelated predicates
    best = max(predicate_score(q_stems, f.predicate) for f in chosen)
    chosen = [f for f in chosen if predicate_score(q_stems, f.predicate) >= best - 1e-9]
    # "Which database does Atlas use?" matches both the verb predicate `uses` and the attribute `database`;
    # the named attribute is what is being asked about, so it wins the tie over a generic verb predicate.
    if any(f.predicate not in VERB_PREDICATES for f in chosen):
        chosen = [f for f in chosen if f.predicate not in VERB_PREDICATES]
    for f in chosen:
        f.subject_key = canon(f.subject_key)
    at = detect_answer_type(query)
    if at and at.strict and not ({f.predicate.split(":")[0] for f in chosen} & at.predicates):
        # e.g. "Which region ...?" must not be answered by "Alice leads Atlas": a fact of the wrong kind is not an answer
        return SlotQuery(rejected=f"the question asks for a {at.name}, but the matching facts are about {sorted({f.predicate for f in chosen})}")
    return SlotQuery(
        facts=chosen, predicates=sorted({f.predicate for f in chosen}), reverse=reverse, assumed_subject=assumed,
        subject_keys=sorted({f.subject_key for f in chosen}),
    )


def is_first_person_text(s: str) -> bool:
    return norm_entity(s) in FIRST_PERSON or norm_entity(s) == "user"
