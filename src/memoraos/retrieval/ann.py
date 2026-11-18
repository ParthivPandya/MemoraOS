"""Inverted-file (IVF) approximate nearest-neighbour index in plain numpy: no extra dependency, deterministic.

Vectors are clustered with spherical k-means; a query scores the centroids, then scores exactly only the vectors in
its ``nprobe`` closest clusters. It trades recall for speed; ``measure_recall`` quantifies that trade on your own
vectors, so the choice is never taken on faith.
"""

from __future__ import annotations

import numpy as np


class IVFIndex:
    def __init__(self, mat: np.ndarray, *, nlist: int | None = None, nprobe: int = 8, iters: int = 8, seed: int = 7):
        n = mat.shape[0]
        self.mat = mat
        self.nlist = max(1, min(nlist or int(np.sqrt(n) * 2), n))
        self.nprobe = max(1, min(nprobe, self.nlist))
        rng = np.random.default_rng(seed)
        self.centroids = mat[rng.choice(n, self.nlist, replace=False)].copy()
        assign = np.zeros(n, dtype=np.int64)
        for _ in range(iters):
            assign = np.argmax(mat @ self.centroids.T, axis=1)
            for c in range(self.nlist):
                members = mat[assign == c]
                if len(members):
                    v = members.sum(axis=0)
                    norm = np.linalg.norm(v)
                    if norm > 0:
                        self.centroids[c] = v / norm
        assign = np.argmax(mat @ self.centroids.T, axis=1)
        order = np.argsort(assign, kind="stable")
        bounds = np.searchsorted(assign[order], np.arange(self.nlist + 1))
        self.lists = [order[bounds[i]: bounds[i + 1]] for i in range(self.nlist)]

    def search(self, q: np.ndarray, k: int, nprobe: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Return (row indices, scores) of the top-k candidates, best first."""
        probe = np.argsort(-(self.centroids @ q))[: nprobe or self.nprobe]
        rows = np.concatenate([self.lists[i] for i in probe]) if len(probe) else np.zeros(0, dtype=np.int64)
        if rows.size == 0:
            return rows, np.zeros(0, dtype=np.float32)
        scores = self.mat[rows] @ q
        top = np.argsort(-scores, kind="stable")[:k]
        return rows[top], scores[top]


def measure_recall(mat: np.ndarray, queries: np.ndarray, k: int, **kw) -> dict:
    """Recall@k of the IVF index against exact search, plus the fraction of vectors scored per query."""
    index = IVFIndex(mat, **kw)
    hit = total = 0
    scored = 0
    for q in queries:
        exact = set(np.argsort(-(mat @ q), kind="stable")[:k].tolist())
        approx, _ = index.search(q, k)
        hit += len(exact & set(approx.tolist()))
        total += len(exact)
        probe = np.argsort(-(index.centroids @ q))[: index.nprobe]
        scored += sum(len(index.lists[i]) for i in probe)
    return {"recall_at_k": hit / max(1, total), "scored_fraction": scored / max(1, len(queries) * mat.shape[0]), "nlist": index.nlist, "nprobe": index.nprobe}
