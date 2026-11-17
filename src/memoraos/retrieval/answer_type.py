"""What kind of value does a question ask for? Used to keep a fact of the wrong kind from answering it."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerType:
    name: str
    predicates: frozenset[str]
    end: str  # "object": the answer is the object of the terminal fact; "subject": the subject
    strict: bool  # strict types must not be answered by facts of any other predicate


LEAD_PREDICATES = frozenset({"leads", "owner", "manager", "lead", "maintainer", "head"})
_TYPES: list[tuple[re.Pattern[str], AnswerType]] = [
    (
        re.compile(r"\bwho\b[^?]*\b(?:leads?|led|manages?|managed|owns?|owned|runs?|heads?|headed|maintains?|maintained)\b|\bwho (?:is|are|was) (?:the |their )?(?:lead|manager|owner|head|maintainer)\b", re.I),
        AnswerType("lead", LEAD_PREDICATES, "subject", True),
    ),
    (re.compile(r"\b(?:region|datacenter|data center)\b|\b(?:hosted|hosting|deployed)\b", re.I), AnswerType("region", frozenset({"hosted_in", "region", "location", "datacenter"}), "object", True)),
    (re.compile(r"\bwhere\b[^?]*\b(?:live|lives|lived|based|reside|resides|stay|stays)\b", re.I), AnswerType("residence", frozenset({"lives_in", "location", "city", "home", "address"}), "object", True)),
    (re.compile(r"\bwhere\b[^?]*\b(?:work|works|worked|employed)\b", re.I), AnswerType("employer", frozenset({"works_at", "employer", "company", "job"}), "object", True)),
]
_ATTRIBUTE = re.compile(r"\b(?:which|what) (database|framework|language|editor|provider|os|stack|version)\b", re.I)


def detect_answer_type(query: str) -> AnswerType | None:
    for rx, at in _TYPES:
        if rx.search(query):
            return at
    m = _ATTRIBUTE.search(query)
    if m:
        attr = m.group(1).lower()
        return AnswerType(attr, frozenset({attr, "uses", "depends_on", "prefers", "building"}), "object", False)
    return None
