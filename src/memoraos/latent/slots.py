"""CPU slot-attention memory: k-means slots plus query-conditioned cross-attention readout."""

from __future__ import annotations

import numpy as np

from .base import LatentMemoryBackend, LatentStats


def _softmax(x: np.ndarray) -> np.ndarray:
    z = x - x.max()
    e = np.exp(z)
    return e / e.sum()


class SlotAttentionMemory(LatentMemoryBackend):
    """EXPERIMENTAL baseline. Compresses N document embeddings into ``n_slots`` vectors.

    * slots: k-means centroids (deterministic, seeded) -- unsupervised, NOT trained for any downstream task
    * readout(q): softmax(q . slots / temperature) weights the slot value vectors, giving a fixed-size
      (n_slots, dim) query-conditioned representation, analogous in shape (not in training) to memory tokens
    * retrieve(q): documents ranked by attention-weighted slot membership times cosine to q, so the source
      documents can always be returned as evidence
    """

    name = "slot-attention-kmeans (experimental)"

    def __init__(self, n_slots: int = 16, temperature: float = 0.1, iterations: int = 20, seed: int = 0):
        if n_slots < 1:
            raise ValueError("n_slots must be >= 1")
        self.n_slots, self.temperature, self.iterations, self.seed = n_slots, temperature, iterations, seed
        self.ids: list[str] = []
        self.emb = np.zeros((0, 0), dtype=np.float32)
        self.slots = np.zeros((0, 0), dtype=np.float32)
        self.values = np.zeros((0, 0), dtype=np.float32)
        self.assign = np.zeros((0, 0), dtype=np.float32)

    def fit(self, doc_ids: list[str], embeddings: np.ndarray) -> None:
        emb = np.asarray(embeddings, dtype=np.float32)
        if emb.ndim != 2 or len(doc_ids) != emb.shape[0]:
            raise ValueError("embeddings must be (n, dim) and match doc_ids")
        self.ids, self.emb = list(doc_ids), emb
        n = emb.shape[0]
        if n == 0:
            self.slots = self.values = np.zeros((0, emb.shape[1] if emb.ndim == 2 else 0), np.float32)
            self.assign = np.zeros((0, 0), np.float32)
            return
        k = min(self.n_slots, n)
        rng = np.random.default_rng(self.seed)
        # k-means++ style deterministic initialisation
        centers = [emb[rng.integers(n)]]
        for _ in range(1, k):
            d2 = np.min(((emb[:, None, :] - np.stack(centers)[None]) ** 2).sum(-1), axis=1)
            probs = d2 / d2.sum() if d2.sum() > 0 else np.full(n, 1 / n)
            centers.append(emb[rng.choice(n, p=probs)])
        c = np.stack(centers)
        for _ in range(self.iterations):
            labels = np.argmax(emb @ c.T, axis=1)
            new = np.stack([emb[labels == j].mean(0) if np.any(labels == j) else c[j] for j in range(k)])
            norms = np.linalg.norm(new, axis=1, keepdims=True)
            new = new / np.where(norms == 0, 1, norms)
            if np.allclose(new, c, atol=1e-6):
                c = new
                break
            c = new
        self.slots = c.astype(np.float32)
        soft = np.apply_along_axis(lambda row: _softmax(row / self.temperature), 1, emb @ self.slots.T)
        self.assign = soft.astype(np.float32)
        weights = self.assign / np.maximum(self.assign.sum(0, keepdims=True), 1e-9)
        self.values = (weights.T @ emb).astype(np.float32)

    def readout(self, query: np.ndarray) -> np.ndarray:
        if self.slots.shape[0] == 0:
            return np.zeros((0, self.emb.shape[1] if self.emb.ndim == 2 else 0), np.float32)
        a = _softmax((self.slots @ np.asarray(query, np.float32)) / self.temperature)
        return (a[:, None] * self.values).astype(np.float32)

    def retrieve(self, query: np.ndarray, k: int) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        q = np.asarray(query, np.float32)
        a = _softmax((self.slots @ q) / self.temperature)
        slot_weight = self.assign @ a
        scores = slot_weight * (self.emb @ q)
        order = np.argsort(-scores, kind="stable")[:k]
        return [(self.ids[i], float(scores[i])) for i in order if scores[i] > 0]

    def stats(self) -> LatentStats:
        n, d = (self.emb.shape if self.emb.ndim == 2 and self.emb.size else (0, 0))
        k = self.slots.shape[0]
        return LatentStats(n, k, d, (n / k) if k else 0.0, self.name)
