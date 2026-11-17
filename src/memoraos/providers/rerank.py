"""Reranker adapters. ``LexicalReranker`` (providers.local) is the deterministic offline default.

* ``CrossEncoderReranker`` - local neural cross-encoder via ``sentence-transformers`` (optional, lazy).
* ``HttpReranker`` - any Cohere/Jina/Voyage-style ``POST /rerank`` endpoint (optional, bring your own key).

Whether reranking helps on YOUR data is an empirical question; see docs/RETRIEVAL.md for the ablation method.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from .base import ProviderError, ProviderUnavailable


class CrossEncoderReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2", *, batch_size: int = 16, model=None):
        self.model_name = model_name
        self.name = f"cross-encoder:{model_name}"
        self.batch_size = batch_size
        self._model = model

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise ProviderUnavailable("sentence-transformers is not installed; run: pip install sentence-transformers") from exc
            try:
                self._model = CrossEncoder(self.model_name)
            except Exception as exc:  # noqa: BLE001
                raise ProviderUnavailable(f"could not load {self.model_name}: {exc}") from exc
        return self._model

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        try:
            scores = self._load().predict([(query, d) for d in documents], batch_size=self.batch_size)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"{self.name}: {exc}") from exc
        return [float(s) for s in scores]


class HttpReranker:
    """``POST {base_url}/rerank`` with ``{model, query, documents}`` -> ``{results: [{index, relevance_score}]}``."""

    def __init__(
        self, model: str, base_url: str, *, api_key: str | None = None, timeout: float = 20.0, max_retries: int = 1,
        client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep,
    ):
        self.name = f"http-rerank:{model}"
        self.model, self.base_url, self.api_key = model, base_url.rstrip("/"), api_key
        self.timeout, self.max_retries, self.sleep = timeout, max_retries, sleep
        self._client = client or httpx.Client(timeout=timeout)

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": self.model, "query": query, "documents": documents, "top_n": len(documents)}
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                r = self._client.post(f"{self.base_url}/rerank", json=payload, headers=headers, timeout=self.timeout)
                if r.status_code >= 500 or r.status_code == 429:
                    raise ProviderError(f"{self.name}: HTTP {r.status_code}")
                if r.status_code >= 400:
                    raise ProviderUnavailable(f"{self.name}: HTTP {r.status_code}")
                scores = [0.0] * len(documents)
                for item in r.json()["results"]:
                    scores[int(item["index"])] = float(item.get("relevance_score", item.get("score", 0.0)))
                return scores
            except ProviderUnavailable:
                raise
            except (httpx.HTTPError, ProviderError) as exc:
                last = exc
                if attempt < self.max_retries:
                    self.sleep(0.2 * (attempt + 1))
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProviderError(f"{self.name}: malformed rerank response") from exc
        raise ProviderError(f"{self.name}: {last}")
