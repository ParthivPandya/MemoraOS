"""Brute-force cosine vector index over SQLite-stored embeddings (no external service)."""

from __future__ import annotations

import numpy as np

from ..models import Scope
from ..storage.db import Database
from ..storage.visibility import visibility_clause
from ..store import Store
from .ann import IVFIndex
from .lexical import Candidate


class VectorIndex:
    def __init__(self, db: Database, store: Store):
        self.db = db
        self.store = store
        self._cache: dict[tuple, tuple[list[str], np.ndarray]] = {}
        self._ann: dict[tuple, IVFIndex] = {}

    def invalidate(self) -> None:
        self._cache.clear()
        self._ann.clear()

    def ensure_embeddings(self, scope: Scope) -> int:
        """Backfill vectors for memories embedded with a different model (incremental re-indexing)."""
        vis, params = visibility_clause(scope, "m")
        self.store.sync_model_version()
        model = self.store.embedder.name
        rows = self.db.query(
            f"SELECT m.id, m.normalized_content FROM memories m WHERE m.status='active' AND {vis}"
            " AND (m.embedding_model IS NULL OR m.embedding_model != ?)",
            [*params, model],
        )
        if not rows:
            return 0
        vecs = self.store.embed_texts([r["normalized_content"] for r in rows])
        with self.db.tx() as conn:
            for r, _ in zip(rows, vecs, strict=True):
                from ..store import content_hash

                conn.execute(
                    "UPDATE memories SET embedding_hash=?, embedding_model=? WHERE id=?",
                    (content_hash(r["normalized_content"]), model, r["id"]),
                )
        self.invalidate()
        return len(rows)

    def _matrix(self, scope: Scope) -> tuple[list[str], np.ndarray]:
        key = (scope.model_dump_json(), self.db.store_version(), self.store.embedder.name)
        hit = self._cache.get(key)
        if hit:
            return hit
        vis, params = visibility_clause(scope, "m")
        rows = self.db.query(
            "SELECT m.id AS id, e.vector AS vector FROM memories m JOIN embeddings e"
            " ON e.content_hash = m.embedding_hash AND e.model = ?"
            f" WHERE m.status='active' AND {vis} ORDER BY m.rowid",
            [self.store.embedder.name, *params],
        )
        ids = [r["id"] for r in rows]
        mat = np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows]) if rows else np.zeros((0, self.store.embedder.dim), np.float32)
        if len(self._cache) > 32:
            self._cache.clear()
        self._cache[key] = (ids, mat)
        return ids, mat

    def search(self, scope: Scope, query: str, k: int, min_score: float = 0.05) -> list[Candidate]:
        self.ensure_embeddings(scope)
        ids, mat = self._matrix(scope)
        if not ids:
            return []
        q = self.store.embed_texts([query], persist=False)[0]
        cfg = self.store.settings
        if cfg.vector_index == "ivf" and len(ids) >= cfg.ann_min_vectors:
            key = (scope.model_dump_json(), self.db.store_version(), self.store.embedder.name)
            index = self._ann.get(key)
            if index is None:
                if len(self._ann) > 4:
                    self._ann.clear()
                index = self._ann[key] = IVFIndex(mat, nprobe=cfg.ann_nprobe)
            rows, scores = index.search(q, k)
            return [Candidate(ids[int(i)], float(s), "vector") for i, s in zip(rows, scores, strict=True) if s >= min_score]
        return top_k_cosine(ids, mat, q, k, min_score)


def top_k_cosine(ids: list[str], mat: np.ndarray, q: np.ndarray, k: int, min_score: float = 0.05) -> list[Candidate]:
    if mat.shape[0] == 0:
        return []
    scores = mat @ q
    order = np.argsort(-scores, kind="stable")[:k]
    return [Candidate(ids[i], float(scores[i]), "vector") for i in order if scores[i] >= min_score]
