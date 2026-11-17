"""Question analysis for evidence fusion: what is asked (answer type), where to start (anchors) and which
relation the question names for the first step (cue). Everything here is deterministic and inspectable."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..retrieval.answer_type import AnswerType, detect_answer_type
from ..retrieval.facts import _entity_in_query
from ..util import STOPWORDS, stem, tokenize

__all__ = ["AnswerType", "Cue", "QuestionPlan", "detect_answer_type", "find_cue", "names_a_chain", "plan_question"]

# verbs that name a relation, as they are written in questions
_VERBS = {
    "leads": r"(?:leads?|led|manages?|managed|owns?|owned|runs?|heads?|headed|maintains?|maintained)",
    "uses": r"(?:uses?|used|using|adopts?|adopted)",
    "depends_on": r"(?:depends? on|relies on|rel(?:y|ies) on)",
    "works_at": r"(?:works? (?:at|for)|employed (?:at|by))",
    "lives_in": r"(?:lives? in|based in)",
}
_PASSIVE = {
    "leads": r"(?:managed|led|owned|headed|run|maintained)",
    "uses": r"(?:used|adopted)",
}
_INVERSE_PASSIVE = {"hosted_in": r"(?:hosted|deployed|running)"}


@dataclass(frozen=True)
class Cue:
    """The relation the question names for the first step away from an anchor."""

    predicate: str
    direction: str  # "out": anchor --predicate--> next ; "in": next --predicate--> anchor
    anchor: str


@dataclass
class QuestionPlan:
    answer: AnswerType | None
    anchors: list[str] = field(default_factory=list)
    cue: Cue | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        """Fusion is for questions that need a chain: a recognised answer type, an anchor, and a named first relation
        that is not itself the answer (otherwise one stored fact suffices and plain fact lookup handles it)."""
        return (
            self.answer is not None and bool(self.anchors) and self.cue is not None
            and self.cue.predicate not in self.answer.predicates
        )


def _surface(key: str) -> str:
    toks = [t for t in tokenize(key) if t not in STOPWORDS] or tokenize(key)
    return r"\W+".join(rf"{re.escape(t)}\w*" for t in toks)


def find_cue(query: str, anchor_key: str) -> Cue | None:
    e = _surface(anchor_key)
    if not e:
        return None
    for pred, verb in _VERBS.items():  # "the project that uses Azure Functions"
        if re.search(rf"\b(?:that|which|who)\s+{verb}\s+(?:the\s+)?{e}", query, re.I):
            return Cue(pred, "in", anchor_key)
    for pred, passive in _INVERSE_PASSIVE.items():  # "the service hosted in West Europe"
        if re.search(rf"\b{passive}\s+(?:in|on|at)\s+(?:the\s+)?{e}", query, re.I):
            return Cue(pred, "in", anchor_key)
    for pred, passive in _PASSIVE.items():  # "the project managed by Alice"
        if re.search(rf"\b{passive}\s+by\s+{e}", query, re.I):
            return Cue(pred, "out", anchor_key)
    for pred, verb in _VERBS.items():  # "the project Alice manages"
        if re.search(rf"\b{e}\s+{verb}\b", query, re.I):
            return Cue(pred, "out", anchor_key)
    return None


def names_a_chain(query: str) -> bool:
    """True when the question text itself asks for a chain: a typed answer reached through a named relation from a
    named entity ("Which region is used by the project Alice manages?"). Independent of what is stored."""
    at = detect_answer_type(query)
    if at is None:
        return False
    for m in re.finditer(r"\b[A-Z][\w.#+\-]*(?:\s+[A-Z][\w.#+\-]*)*", query):
        name = m.group(0)
        if name.lower() in STOPWORDS:
            continue
        cue = find_cue(query, name.lower())
        if cue is not None and cue.predicate not in at.predicates:
            return True
    return False


def plan_question(query: str, entity_keys: Iterable[str]) -> QuestionPlan:
    answer = detect_answer_type(query)
    q_stems = {stem(t) for t in tokenize(query)}
    q_text = query.lower()
    hits = sorted((k for k in set(entity_keys) if k != "user" and _entity_in_query(k, q_stems, q_text)), key=lambda k: (-len(k), k))
    anchors = [k for k in hits if not any(k != o and k in o for o in hits)]
    plan = QuestionPlan(answer=answer, anchors=anchors)
    if answer is None:
        plan.reasons.append("no recognised answer type")
        return plan
    plan.reasons.append(f"answer type '{answer.name}' -> {sorted(answer.predicates)} ({answer.end})")
    for a in anchors:
        cue = find_cue(query, a)
        if cue:
            plan.cue = cue
            plan.reasons.append(f"first step from '{a}': {cue.predicate} ({cue.direction})")
            break
    if not anchors:
        plan.reasons.append("no known entity named in the question")
    elif plan.cue is None:
        plan.reasons.append("question names no relation from the anchor")
    return plan
