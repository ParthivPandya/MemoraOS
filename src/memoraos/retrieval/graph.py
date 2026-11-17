"""Relational memory: a NetworkX graph built on demand from visible facts and entity co-mentions."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import networkx as nx

from ..ingestion.extract import norm_entity
from ..ingestion.lexicon import RELATIONAL_PREDICATES, query_stems
from ..models import Scope
from ..storage.db import Database
from ..storage.visibility import visibility_clause
from .facts import _entity_in_query, load_aliases, load_facts
from .lexical import Candidate

MENTION_EDGE_COST = 2.0
FACT_EDGE_COST = 1.0
MAX_MENTIONS_PER_MEMORY = 12


@dataclass
class Edge:
    src: str
    dst: str
    predicate: str
    memory_id: str
    kind: str  # fact | mention

    def text(self, names: dict[str, str]) -> str:
        a, b = names.get(self.src, self.src), names.get(self.dst, self.dst)
        return f"{a} -[{self.predicate}]-> {b}" if self.kind == "fact" else f"{a} ~ {b} (co-mentioned)"


@dataclass
class GraphResult:
    candidates: list[Candidate] = field(default_factory=list)
    paths: list[list[Edge]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)

    def describe(self) -> list[str]:
        return list(dict.fromkeys(" ; ".join(e.text(self.names) for e in p) for p in self.paths))


def build_graph(db: Database, scope: Scope, as_of: str | None = None) -> tuple[nx.Graph, dict[str, str]]:
    aliases = load_aliases(db, scope)

    def canon(k: str) -> str:
        return aliases.get(k, k)

    g = nx.Graph()
    names: dict[str, str] = {}
    for f in load_facts(db, scope, as_of=as_of):
        if f.predicate not in RELATIONAL_PREDICATES or len(f.object.split()) > 4:
            continue
        a, b = canon(f.subject_key), canon(norm_entity(f.object))
        if not a or not b or a == b:
            continue
        names.setdefault(a, f.subject if a != "user" else "user")
        names.setdefault(b, f.object)
        _add_edge(g, Edge(a, b, f.predicate, f.memory_id, "fact"), FACT_EDGE_COST)
    vis, params = visibility_clause(scope, "n")
    sys_sql = ""
    args = list(params)
    if as_of:
        sys_sql = " AND m.created_at <= ?"
        args.append(as_of)
    rows = db.query(
        "SELECT n.memory_id, n.entity_key, n.entity_name FROM mentions n JOIN memories m ON m.id = n.memory_id"
        f" WHERE m.status='active' AND {vis}{sys_sql} ORDER BY n.memory_id",
        args,
    )
    per: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        per.setdefault(r["memory_id"], []).append((canon(r["entity_key"]), r["entity_name"]))
    for mid, ents in per.items():
        if len(ents) > MAX_MENTIONS_PER_MEMORY:
            continue
        for k, n in ents:
            names.setdefault(k, n)
        for (ka, _), (kb, _) in combinations(sorted(set(ents)), 2):
            if ka != kb:
                _add_edge(g, Edge(ka, kb, "mentions", mid, "mention"), MENTION_EDGE_COST)
    return g, names


def _add_edge(g: nx.Graph, e: Edge, cost: float) -> None:
    if g.has_edge(e.src, e.dst):
        data = g[e.src][e.dst]
        data["edges"].append(e)
        data["weight"] = min(data["weight"], cost)
    else:
        g.add_edge(e.src, e.dst, edges=[e], weight=cost)


def query_entities(g: nx.Graph, query: str) -> list[str]:
    q_stems = query_stems(query)
    q_text = query.lower()
    hits = [n for n in g.nodes if n != "user" and _entity_in_query(n, q_stems, q_text)]
    hits.sort(key=lambda n: (-len(n), n))
    # drop entities fully contained in a longer matched entity (e.g. "azure" inside "azure functions")
    return [n for n in hits if not any(n != m and n in m for m in hits)]


def _path_edges(g: nx.Graph, nodes: list[str]) -> list[Edge]:
    edges = []
    for a, b in zip(nodes, nodes[1:], strict=False):
        cands = g[a][b]["edges"]
        fact = [e for e in cands if e.kind == "fact"]
        edges.append((fact or cands)[0])
    return edges


def graph_retrieve(db: Database, scope: Scope, query: str, *, max_hops: int, k: int, as_of: str | None = None) -> GraphResult:
    g, names = build_graph(db, scope, as_of)
    ents = query_entities(g, query)
    res = GraphResult(entities=ents, names=names)
    if not ents:
        return res
    scores: dict[str, float] = {}
    order: list[str] = []

    def credit(edges: list[Edge], base: float) -> None:
        for i, e in enumerate(edges):
            s = base / (1 + 0.05 * i) * (1.0 if e.kind == "fact" else 0.6)
            if e.memory_id not in scores:
                order.append(e.memory_id)
            scores[e.memory_id] = max(scores.get(e.memory_id, 0.0), s)

    if len(ents) >= 2:
        for a, b in combinations(ents, 2):
            if not (nx.has_path(g, a, b)):
                continue
            nodes = nx.shortest_path(g, a, b, weight="weight")
            if len(nodes) - 1 > max_hops:
                continue
            edges = _path_edges(g, nodes)
            res.paths.append(edges)
            credit(edges, 1.0)
    if not res.paths:
        for src in ents[:2]:
            dist = nx.single_source_dijkstra_path(g, src, cutoff=max_hops * MENTION_EDGE_COST, weight="weight")
            for _node, path in sorted(dist.items(), key=lambda kv: (len(kv[1]), kv[0])):
                if len(path) < 2 or len(path) - 1 > max_hops:
                    continue
                edges = _path_edges(g, path)
                res.paths.append(edges)
                credit(edges, 1.0 / len(edges))
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], order.index(kv[0])))[:k]
    res.candidates = [Candidate(mid, s, "graph") for mid, s in ranked]
    return res
