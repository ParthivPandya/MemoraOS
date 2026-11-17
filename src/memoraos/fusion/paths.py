"""Evidence fusion: answer a multi-hop question by searching typed, validated paths through stored facts.

Instead of retrieving passages that mention the entities, the question is turned into a constraint
(start at the anchor, take the named first relation, end on a fact of the requested type) and every
chain that satisfies it is enumerated within hard bounds. Each step must be a stored fact that is valid at the
requested time, followed in the right direction, without revisiting an entity, and backed by a source memory.
One terminal value gives an answer; several give a conflict/ambiguity; none gives insufficient evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ingestion.extract import norm_entity
from ..ingestion.lexicon import RELATIONAL_PREDICATES
from ..models import Fact, Scope
from ..retrieval.answer_type import AnswerType
from ..retrieval.facts import load_aliases, load_facts
from ..storage.db import Database
from ..truth.timeline import build_timeline
from .plan import QuestionPlan, plan_question

MIN_HOPS = 2
MAX_OBJECT_WORDS = 4


@dataclass
class Edge:
    src: str
    dst: str
    predicate: str
    fact: Fact
    conflicted: bool = False


@dataclass
class Step:
    edge: Edge
    reverse: bool  # traversed against the stored direction (only allowed where the question asks for it)

    @property
    def start(self) -> str:
        return self.edge.dst if self.reverse else self.edge.src

    @property
    def end(self) -> str:
        return self.edge.src if self.reverse else self.edge.dst


@dataclass
class FusionPath:
    steps: list[Step]
    terminal: str

    @property
    def conflicted(self) -> bool:
        return any(s.edge.conflicted for s in self.steps)

    @property
    def facts(self) -> list[Fact]:
        return [s.edge.fact for s in self.steps]

    @property
    def confidence(self) -> float:
        return min(f.extraction_confidence for f in self.facts)


@dataclass
class FusionResult:
    status: str  # answered | conflict | insufficient_evidence
    answer: str = ""
    values: list[str] = field(default_factory=list)
    paths: list[FusionPath] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    confidence: float | None = None
    reliability: float | None = None
    trace: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    plan: QuestionPlan | None = None
    truncated: bool = False


class EvidenceGraph:
    """Directed fact graph valid at one point in time. Conflicting single-valued facts stay visible as flagged edges."""

    def __init__(self) -> None:
        self.out: dict[str, list[Edge]] = {}
        self.into: dict[str, list[Edge]] = {}
        self.names: dict[str, str] = {}

    def add(self, e: Edge) -> None:
        self.out.setdefault(e.src, []).append(e)
        self.into.setdefault(e.dst, []).append(e)

    @property
    def nodes(self) -> set[str]:
        return set(self.out) | set(self.into)


def build_evidence_graph(db: Database, scope: Scope, when: str, as_of: str | None = None) -> EvidenceGraph:
    aliases = load_aliases(db, scope)

    def canon(k: str) -> str:
        return aliases.get(k, k)

    groups: dict[tuple, list[Fact]] = {}
    for f in load_facts(db, scope, as_of=as_of):
        if f.subject_key in ("unspecified", "") or f.predicate == "is":
            continue
        key = (f.subject_key, f.slot) if f.slot else (f.subject_key, f.predicate, f.object_key)
        groups.setdefault(key, []).append(f)
    g = EvidenceGraph()
    for fs in groups.values():
        cur = build_timeline(fs).at(when)
        if not cur:
            continue  # not valid at the requested time
        runs, conflicted = cur
        for run in runs:
            f = run.facts[-1]
            if not f.memory_id:
                continue  # provenance: a step must point at a stored memory
            relational = f.predicate in RELATIONAL_PREDICATES
            if relational and len(f.object.split()) > MAX_OBJECT_WORDS:
                continue
            src = canon(f.subject_key)
            dst = canon(norm_entity(f.object)) if relational else canon(f.object_key)
            if not src or not dst or src == dst:
                continue
            g.names.setdefault(src, f.subject if src != "user" else "you")
            g.names.setdefault(dst, f.object)
            g.add(Edge(src, dst, f.predicate, f, conflicted))
    return g


def search_paths(g: EvidenceGraph, plan: QuestionPlan, *, max_hops: int, max_paths: int, max_expansions: int) -> tuple[list[FusionPath], bool]:
    """Enumerate simple paths matching the plan. Returns (paths, truncated)."""
    ans: AnswerType = plan.answer  # type: ignore[assignment]
    cue = plan.cue
    if cue is None:
        return [], False
    paths: list[FusionPath] = []
    budget = {"left": max_expansions, "truncated": False}

    def ordered(edges: list[Edge]) -> list[Edge]:
        return sorted(edges, key=lambda e: (e.predicate, e.src, e.dst, e.fact.id))

    def candidate_steps(node: str, depth: int) -> list[tuple[Step, bool]]:
        """(step, is_terminal) moves from ``node``."""
        moves: list[tuple[Step, bool]] = []
        if depth == 0:
            pool = g.into if cue.direction == "in" else g.out
            for e in ordered([e for e in pool.get(node, []) if e.predicate == cue.predicate]):
                moves.append((Step(e, reverse=cue.direction == "in"), False))
            return moves
        for e in ordered(g.out.get(node, [])):
            terminal = ans.end == "object" and e.predicate in ans.predicates
            if terminal or e.predicate in RELATIONAL_PREDICATES:
                moves.append((Step(e, reverse=False), terminal))
        if ans.end == "subject":
            for e in ordered([e for e in g.into.get(node, []) if e.predicate in ans.predicates]):
                moves.append((Step(e, reverse=True), True))
        return moves

    def dfs(node: str, steps: list[Step], visited: frozenset[str]) -> None:
        if len(paths) >= max_paths:
            budget["truncated"] = True
            return
        for step, terminal in candidate_steps(node, len(steps)):
            budget["left"] -= 1
            if budget["left"] < 0:
                budget["truncated"] = True
                return
            nxt = step.end
            if nxt in visited:
                continue  # never revisit an entity
            new_steps = [*steps, step]
            if terminal and len(new_steps) >= MIN_HOPS:
                paths.append(FusionPath(new_steps, nxt))
                if len(paths) >= max_paths:
                    budget["truncated"] = True
                    return
                continue  # the answer edge ends the chain
            if len(new_steps) < max_hops:
                dfs(nxt, new_steps, visited | {nxt})

    dfs(cue.anchor, [], frozenset({cue.anchor}))
    return paths, bool(budget["truncated"])


def _label(predicate: str) -> str:
    return predicate.split(":")[0].replace("_", " ")


def render_path(p: FusionPath, names: dict[str, str]) -> str:
    out = [names.get(p.steps[0].start, p.steps[0].start)]
    for s in p.steps:
        arrow = f"<-[{_label(s.edge.predicate)}]-" if s.reverse else f"-[{_label(s.edge.predicate)}]->"
        out.append(f"{arrow} {names.get(s.end, s.end)}")
    return " ".join(out)


def evidence_fusion(
    db: Database, scope: Scope, query: str, *, when: str, as_of: str | None = None, max_hops: int = 4, max_paths: int = 50,
    max_expansions: int = 5000, graph: EvidenceGraph | None = None,
) -> FusionResult:
    g = graph or build_evidence_graph(db, scope, when, as_of)
    plan = plan_question(query, g.nodes)
    res = FusionResult("insufficient_evidence", plan=plan, notes=list(plan.reasons))
    if not plan.applicable:
        res.notes.append("evidence fusion not applicable to this question")
        return res
    paths, truncated = search_paths(g, plan, max_hops=max_hops, max_paths=max_paths, max_expansions=max_expansions)
    res.truncated = truncated
    if truncated:
        res.notes.append(f"search stopped at its bound ({max_paths} paths / {max_expansions} expansions); results may be incomplete")
    if not paths:
        res.notes.append("no chain of stored facts connects the anchor to a fact of the requested type")
        return res
    by_value: dict[str, list[FusionPath]] = {}
    for p in sorted(paths, key=lambda p: (len(p.steps), -p.confidence)):
        by_value.setdefault(p.terminal, []).append(p)
    res.paths = [ps[0] for ps in by_value.values()]
    res.values = [g.names.get(k, k) for k in by_value]
    res.trace = [render_path(p, g.names) for p in res.paths]
    used: list[Fact] = []
    for p in res.paths:
        used.extend(f for f in p.facts if f.id not in {u.id for u in used})
    res.facts = used
    res.confidence = min(p.confidence for p in res.paths)
    res.reliability = min(f.source_reliability for f in used)
    conflicted = any(p.conflicted for p in res.paths)
    if len(by_value) == 1 and not conflicted:
        res.status, res.answer = "answered", res.values[0]
        return res
    why = "a step is contradicted by another stored fact" if conflicted else "several different chains of facts lead to different answers"
    res.status = "conflict"
    res.answer = f"The stored facts do not establish a single answer ({why}): " + " | ".join(f"{v} (via {t})" for v, t in zip(res.values, res.trace, strict=True))
    return res
