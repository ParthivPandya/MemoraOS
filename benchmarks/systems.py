"""Systems under test: in-repo baselines, MemoraOS, and probes for external systems."""

from __future__ import annotations

import importlib.util
import itertools
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from memoraos import MemoryOS
from memoraos.ingestion.classify import chunk_text
from memoraos.providers.local import HashingEmbedder
from memoraos.retrieval.fusion import rrf
from memoraos.retrieval.lexical import Candidate, PyBM25
from memoraos.retrieval.vector import top_k_cosine
from memoraos.routing.router import analyze_query
from memoraos.truth.answer import compose_passage_answer
from memoraos.util import estimate_tokens

from .datasets import Event, Question

TOP_K = 5
READER_SENTENCES = 3
MIN_COVERAGE = 0.5  # same threshold MemoraOS uses by default


@dataclass
class Response:
    answer: str
    evidence_events: list[int]
    excerpts: list[str]
    supported: bool
    flagged_conflict: bool
    context_tokens: int
    latency_ms: float
    strategy: str = ""


class FakeClock:
    def __init__(self):
        self.now = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def set(self, iso: str) -> None:
        self.now = datetime.fromisoformat(iso)

    def __call__(self) -> datetime:
        self.now += timedelta(microseconds=1)
        return self.now


class System:
    name = "system"
    description = ""
    supports_restart = True

    def ingest(self, events: list[Event]) -> float:
        """Apply events in order; returns total seconds spent."""
        t0 = time.perf_counter()
        for e in events:
            if e.kind == "add":
                self.add(e)
            else:
                self.correct(e)
        return time.perf_counter() - t0

    def add(self, e: Event) -> None: ...
    def correct(self, e: Event) -> None: ...
    def ask(self, q: Question) -> Response: ...
    def storage_bytes(self) -> int:
        return 0

    def restart(self) -> float:
        return 0.0

    def close(self) -> None: ...


# --------------------------------------------------------------------------------------------
# baselines: classical RAG built from the same primitives, with a shared extractive reader
# --------------------------------------------------------------------------------------------
@dataclass
class _Doc:
    event: int
    text: str
    user: str
    recorded_at: str


class RagBaseline(System):
    """mode: bm25 | vector | hybrid. ``gate`` adds the same coverage-based abstention MemoraOS uses."""

    def __init__(self, mode: str, gate: bool = False, reader_sentences: int = READER_SENTENCES, embedder=None, label: str | None = None):
        self.mode, self.gate, self.reader_sentences = mode, gate, reader_sentences
        self.name = {"bm25": "bm25", "vector": "vector", "hybrid": "hybrid_rag"}[mode] + ("_top1" if reader_sentences == 1 else "") + ("_gated" if gate else "")
        self.description = {
            "bm25": "Okapi BM25 over chunks, extractive reader",
            "vector": "Cosine over hashing embeddings, extractive reader",
            "hybrid": "BM25 + vector with reciprocal rank fusion, extractive reader",
        }[mode] + (" returning only the single best sentence" if reader_sentences == 1 else f" returning up to {reader_sentences} best sentences") + ("; abstains when evidence covers <50% of question terms" if gate else "; always answers")
        self.embedder = embedder or HashingEmbedder(512)
        self._dim = self.embedder.dim
        if label:
            self.name = label
        self.docs: list[_Doc] = []
        self.vecs = np.zeros((0, self._dim), np.float32)
        self._bm25: dict[tuple, PyBM25] = {}
        self.event_chunks: dict[int, list[int]] = {}
        self._raw: list[Event] = []

    def _chunks(self, text: str) -> list[str]:
        return chunk_text(text, 800, 100) or [text]

    def add(self, e: Event) -> None:
        self._raw.append(e)
        parts = self._chunks(e.text)
        vs = self.embedder.embed(parts)
        for p in parts:
            self.docs.append(_Doc(e.idx, p, e.user, e.recorded_at))
        self.vecs = np.vstack([self.vecs, vs]) if self.vecs.size else vs
        self._bm25.clear()

    def correct(self, e: Event) -> None:  # in-place upsert of the original document
        keep = [i for i, d in enumerate(self.docs) if d.event != e.target]
        self.docs = [self.docs[i] for i in keep]
        self.vecs = self.vecs[keep] if keep else np.zeros((0, self._dim), np.float32)
        self._bm25.clear()
        parts = self._chunks(e.text)
        for p in parts:
            self.docs.append(_Doc(e.target if e.target is not None else e.idx, p, e.user, e.recorded_at))
        vs = self.embedder.embed(parts)
        self.vecs = np.vstack([self.vecs, vs]) if self.vecs.size else vs

    def ask(self, q: Question) -> Response:
        t0 = time.perf_counter()
        mask = [i for i, d in enumerate(self.docs) if d.user == q.user and (q.as_of is None or d.recorded_at <= q.as_of)]
        if not mask:
            return Response("", [], [], False, False, 0, (time.perf_counter() - t0) * 1000)
        ids = [str(i) for i in mask]
        lists: dict[str, list[Candidate]] = {}
        if self.mode in ("bm25", "hybrid"):
            key = (q.user, q.as_of)
            if key not in self._bm25:
                self._bm25[key] = PyBM25({str(i): self.docs[i].text for i in mask})
            lists["bm25"] = self._bm25[key].search(q.text, TOP_K * 4)
        if self.mode in ("vector", "hybrid"):
            qv = self.embedder.embed([q.text])[0]
            lists["vector"] = top_k_cosine(ids, self.vecs[mask], qv, TOP_K * 4)
        ranked = lists[self.mode] if self.mode != "hybrid" else rrf(lists, 60)
        top = ranked[:TOP_K]
        passages = [(c.memory_id, self.docs[int(c.memory_id)].text) for c in top]
        terms = analyze_query(q.text).terms
        pa = compose_passage_answer(terms, passages, max_sentences=self.reader_sentences)
        supported = bool(top) and (not self.gate or (pa.text != "" and pa.coverage >= MIN_COVERAGE))
        answer = pa.text if pa.text else (passages[0][1] if passages and not self.gate else "")
        events, seen = [], set()
        for c in top:
            ev = self.docs[int(c.memory_id)].event
            if ev not in seen:
                seen.add(ev)
                events.append(ev)
        ctx = estimate_tokens(" ".join(p for _, p in passages)) if supported else 0
        excerpts = [p for _, p in passages]
        return Response(answer if supported else "", events if supported else [], excerpts if supported else [], supported, False, ctx, (time.perf_counter() - t0) * 1000, self.mode)

    def storage_bytes(self) -> int:
        return sum(len(d.text.encode()) for d in self.docs) + int(self.vecs.nbytes)

    def restart(self) -> float:
        """A vector/BM25 index held in memory is rebuilt from the raw documents after a restart."""
        t0 = time.perf_counter()
        raw = self._raw
        self.docs, self.vecs, self._bm25, self._raw = [], np.zeros((0, self._dim), np.float32), {}, []
        for e in raw:
            self.add(e)
        return time.perf_counter() - t0


# --------------------------------------------------------------------------------------------
# MemoraOS
# --------------------------------------------------------------------------------------------
class MemoraSystem(System):
    def __init__(self, force_strategy: str | None = None, label: str | None = None, settings=None, reranker=None, description: str | None = None, embedder=None):
        self.embedder = embedder
        self.force = force_strategy
        self.settings = settings
        self.reranker = reranker
        self.name = label or "memoraos"
        self.description = description or "MemoraOS " + (f"with strategy forced to '{force_strategy}' (router and fact engine disabled)" if force_strategy else "full pipeline: router + truth engine + fallbacks")
        self.dir = tempfile.mkdtemp(prefix="memoraos-bench-")
        self.clock = FakeClock()
        self._counter = itertools.count(1)
        self.eng = self._open()
        self.mem_to_event: dict[str, int] = {}
        self.event_to_mem: dict[int, str] = {}

    def _open(self) -> MemoryOS:
        kw = {"reranker": self.reranker} if self.reranker is not None else {}
        if self.embedder is not None:
            kw["embedder"] = self.embedder
        return MemoryOS.local(self.dir, settings=self.settings, clock=self.clock, id_factory=lambda p: f"{p}_{next(self._counter):07d}", **kw)

    def add(self, e: Event) -> None:
        self.clock.set(e.recorded_at)
        r = self.eng.remember(e.text, user_id=e.user, tenant_id="bench", source_type=e.source_type, effective_at=e.effective_at, session_id=None)
        for m in r.memory_ids:
            self.mem_to_event.setdefault(m, e.idx)
        self.event_to_mem[e.idx] = r.memory_ids[0]

    def correct(self, e: Event) -> None:
        self.clock.set(e.recorded_at)
        assert e.target is not None
        self.eng.correct(self.event_to_mem[e.target], e.text, user_id=e.user, tenant_id="bench", reason="benchmark correction")

    def ask(self, q: Question) -> Response:
        r = self.eng.recall(q.text, user_id=q.user, tenant_id="bench", as_of=q.as_of, strategy=self.force, top_k=TOP_K, use_cache=False)
        events, seen = [], set()
        for ev in r.evidence:
            idx = self.mem_to_event.get(ev.memory_id)
            if idx is not None and idx not in seen:
                seen.add(idx)
                events.append(idx)
        return Response(r.answer if r.supported else "", events, [e.excerpt for e in r.evidence], r.supported, r.status == "conflict", r.context_tokens, r.latency_ms, r.strategy)

    def consolidate(self, user: str) -> dict:
        return self.eng.consolidate(user_id=user, tenant_id="bench")

    def storage_bytes(self) -> int:
        self.eng.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return Path(self.eng.db.path).stat().st_size

    def restart(self) -> float:
        t0 = time.perf_counter()
        self.eng.close()
        self.eng = self._open()
        return time.perf_counter() - t0

    def close(self) -> None:
        try:
            self.eng.close()
        finally:
            import shutil

            shutil.rmtree(self.dir, ignore_errors=True)


# --------------------------------------------------------------------------------------------
# external systems: availability probes only (no fabricated numbers)
# --------------------------------------------------------------------------------------------
@dataclass
class ExternalProbe:
    name: str
    module: str
    requirement: str
    notes: str
    status: str = field(default="")

    def probe(self) -> dict:
        installed = importlib.util.find_spec(self.module) is not None
        if not installed:
            reason = f"python package '{self.module}' is not installed"
        else:
            reason = "package present, but no verified adapter exists in this repository yet"
        return {
            "system": self.name, "executed": False, "reason": reason, "requirement": self.requirement, "notes": self.notes,
            "package_installed": installed, "adapter_implemented": False,
            "api_key_in_environment": bool(os.environ.get("OPENAI_API_KEY")),
        }


EXTERNAL = [
    ExternalProbe("Mem0", "mem0", "an LLM for fact extraction and an embedder (default OpenAI) or a local Ollama setup", "Apache-2.0; https://github.com/mem0ai/mem0"),
    ExternalProbe("Graphiti (Zep)", "graphiti_core", "an LLM plus a graph database server (Neo4j / FalkorDB / Kuzu)", "Apache-2.0; https://github.com/getzep/graphiti"),
    ExternalProbe("Hindsight", "hindsight_api", "an LLM provider and its embedded or external PostgreSQL", "MIT; https://github.com/vectorize-io/hindsight"),
    ExternalProbe("Memorilla", "memorilla", "a Linux CUDA GPU (~80 GB for the reference demo), Python 3.11, and downloaded Qwen3 checkpoints", "Apache-2.0; https://github.com/snap-stanford/memorilla; learned latent memory needs a trained module"),
]


def available_systems(include_ablation: bool = True) -> list[System]:
    systems: list[System] = [RagBaseline("bm25"), RagBaseline("vector"), RagBaseline("hybrid"), RagBaseline("hybrid", reader_sentences=1), RagBaseline("hybrid", gate=True), MemoraSystem()]
    if include_ablation:
        systems.append(MemoraSystem(force_strategy="hybrid", label="memoraos_hybrid_only"))
    return systems

