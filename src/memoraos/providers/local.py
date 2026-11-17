"""Default zero-dependency, zero-cost providers.

``HashingEmbedder`` is a *lexical* feature-hashing embedder (word unigrams, bigrams and character
trigrams). It is deterministic and offline, but it does not understand meaning the way a trained
neural embedder does. Swap in an Ollama / OpenAI-compatible embedder for true semantic recall.
"""

from __future__ import annotations

import hashlib
import math
import re

import numpy as np

from ..util import STOPWORDS, stem, tokenize
from .embeddings import BaseEmbeddingProvider


class HashingEmbedder(BaseEmbeddingProvider):
    name = "hashing-v1"
    provider = "local-hashing"
    model_version = "1"

    def __init__(self, dim: int = 512):
        self.dim = dim

    @staticmethod
    def _h(feature: str) -> int:
        return int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "little")

    def _features(self, text: str) -> dict[str, float]:
        toks = [stem(t) for t in tokenize(text) if t not in STOPWORDS]
        feats: dict[str, float] = {}
        for t in toks:
            feats[f"w:{t}"] = feats.get(f"w:{t}", 0.0) + 1.0
        for a, b in zip(toks, toks[1:], strict=False):
            feats[f"b:{a}_{b}"] = feats.get(f"b:{a}_{b}", 0.0) + 0.7
        for t in toks:
            padded = f"#{t}#"
            for i in range(len(padded) - 2):
                key = f"c:{padded[i : i + 3]}"
                feats[key] = feats.get(key, 0.0) + 0.25
        return feats

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for feat, weight in self._features(text).items():
                h = self._h(feat)
                sign = 1.0 if (h >> 63) & 1 else -1.0
                out[i, h % self.dim] += sign * math.sqrt(weight)
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out


class LexicalReranker:
    """Deterministic reranker: fraction of query terms present in the document."""

    name = "lexical-coverage"

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        q = {stem(t) for t in tokenize(query) if t not in STOPWORDS}
        if not q:
            return [0.0] * len(documents)
        scores = []
        for d in documents:
            dt = {stem(t) for t in tokenize(d)}
            scores.append(len(q & dt) / len(q))
        return scores


_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]
