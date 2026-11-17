"""Plug a latent backend into MemoryOS retrieval and measure what it preserves."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from ..models import Scope
from ..retrieval.lexical import Candidate
from ..storage.visibility import visibility_clause
from .base import LatentMemoryBackend
from .slots import SlotAttentionMemory

if TYPE_CHECKING:
    from ..engine import MemoryOS


class LatentIndex:
    """Builds a per-scope latent memory lazily and exposes it as a retrieval strategy ('latent')."""

    def __init__(self, engine: MemoryOS, backend_factory=None, n_slots: int = 16):
        self.engine = engine
        self.factory = backend_factory or (lambda: SlotAttentionMemory(n_slots=n_slots))
        self._cache: dict[tuple, LatentMemoryBackend] = {}

    def backend_for(self, scope: Scope) -> LatentMemoryBackend:
        db, store = self.engine.db, self.engine.store
        key = (scope.model_dump_json(), db.store_version())
        if key in self._cache:
            return self._cache[key]
        vis, params = visibility_clause(scope, "m")
        rows = db.query(f"SELECT m.id, m.normalized_content FROM memories m WHERE m.status='active' AND {vis} ORDER BY m.rowid", params)
        backend = self.factory()
        if rows:
            vecs = store.embed_texts([r["normalized_content"] for r in rows])
            backend.fit([r["id"] for r in rows], np.asarray(vecs))
        else:
            backend.fit([], np.zeros((0, store.embedder.dim), np.float32))
        self._cache = {key: backend}
        return backend

    def candidates(self, scope: Scope, query: str, k: int) -> list[Candidate]:
        backend = self.backend_for(scope)
        q = self.engine.store.embed_texts([query], persist=False)[0]
        return [Candidate(mid, s, "latent") for mid, s in backend.retrieve(q, k)]


def evaluate_information_preservation(
    backend: LatentMemoryBackend, doc_ids: Sequence[str], embeddings: np.ndarray, queries: np.ndarray, gold: Sequence[str], k: int = 5
) -> dict:
    """Compare retrieval through the latent memory against exact cosine search over the same embeddings.

    Reports measured numbers only; they describe this backend on this data, nothing more.
    """
    backend.fit(list(doc_ids), embeddings)
    ids = list(doc_ids)
    exact_hits = latent_hits = 0
    recon = []
    for q, g in zip(queries, gold, strict=True):
        exact = [ids[i] for i in np.argsort(-(embeddings @ q), kind="stable")[:k]]
        lat = [d for d, _ in backend.retrieve(q, k)]
        exact_hits += g in exact
        latent_hits += g in lat
        gi = ids.index(g)
        r = backend.readout(q).sum(0)
        denom = np.linalg.norm(r) * np.linalg.norm(embeddings[gi])
        recon.append(float(r @ embeddings[gi] / denom) if denom else 0.0)
    n = max(1, len(gold))
    s = backend.stats()
    return {
        "backend": s.backend, "n_documents": s.n_documents, "n_slots": s.n_slots, "compression_ratio": round(s.compression_ratio, 2),
        "recall_at_k_exact_cosine": exact_hits / n, "recall_at_k_latent": latent_hits / n,
        "mean_readout_cosine_to_gold": float(np.mean(recon)) if recon else 0.0, "k": k, "n_queries": len(gold),
    }
