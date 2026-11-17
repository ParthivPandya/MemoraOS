"""Embedding provider contract v2: model metadata, health checks and an adapter for v0.1-style providers.

A v0.1 provider only needs ``name``, ``dim`` and ``embed(texts)``; ``adapt_embedder`` wraps it so the rest of the
engine can rely on the richer interface. New providers should subclass ``BaseEmbeddingProvider``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

import numpy as np

from .base import ProviderError, ProviderUnavailable


class EmbeddingModelMismatch(RuntimeError):
    """Vectors of a different size were produced under a model name that already has stored vectors.

    Mixing them would silently corrupt similarity search, so ingestion stops until the index is rebuilt
    (``MemoryOS.reembed(force=True)``) or a different model name is configured.
    """


@dataclass(frozen=True)
class ModelInfo:
    model: str  # unique key; vectors are cached and searched per model
    provider: str
    dim: int
    version: str = ""
    normalization: str = "l2"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str = ""
    latency_ms: float = 0.0


class BaseEmbeddingProvider(ABC):
    name: str = "embedder"
    dim: int = 0
    provider: str = "custom"
    model_version: str = ""
    normalization: str = "l2"

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """(n, dim) float32 matrix, L2-normalised."""

    def embed_text(self, text: str) -> np.ndarray:
        return self.embed_batch([text])[0]

    def embed(self, texts: list[str]) -> np.ndarray:
        """v0.1 name for ``embed_batch``; kept so existing callers keep working."""
        return self.embed_batch(texts)

    def get_embedding_dimension(self) -> int:
        return int(self.dim)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(self.name, self.provider, self.get_embedding_dimension(), self.model_version, self.normalization)

    def health_check(self) -> HealthStatus:
        t0 = time.perf_counter()
        try:
            vec = self.embed_text("health check")
        except Exception as exc:  # noqa: BLE001 - a health probe reports, it never raises
            return HealthStatus(False, f"{type(exc).__name__}: {exc}"[:200], (time.perf_counter() - t0) * 1000)
        ok = bool(np.all(np.isfinite(vec))) and vec.shape[-1] > 0
        return HealthStatus(ok, "" if ok else "non-finite or empty vector", (time.perf_counter() - t0) * 1000)


class LegacyEmbedderAdapter(BaseEmbeddingProvider):
    """Gives a v0.1 provider (``name``, ``dim``, ``embed``) the v2 interface without changing it."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.provider = self.name.split(":", 1)[0] if ":" in self.name else self.name
        self.model_version = getattr(inner, "model_version", "")

    @property
    def dim(self) -> int:  # type: ignore[override]
        return int(self.inner.dim)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return self.inner.embed(texts)

    def health_check(self) -> HealthStatus:
        probe = getattr(self.inner, "health_check", None)
        if callable(probe):
            return probe()
        avail = getattr(self.inner, "is_available", None)
        if callable(avail):
            ok = bool(avail())
            return HealthStatus(ok, "" if ok else "provider reports unavailable")
        return super().health_check()


def adapt_embedder(embedder) -> BaseEmbeddingProvider:
    if isinstance(embedder, BaseEmbeddingProvider):
        return embedder
    for attr in ("name", "dim", "embed"):
        if not hasattr(embedder, attr):
            raise TypeError(f"embedding provider is missing '{attr}'")
    return LegacyEmbedderAdapter(embedder)


class SentenceTransformerEmbedder(BaseEmbeddingProvider):
    """Local neural embeddings via ``sentence-transformers`` (optional: ``pip install sentence-transformers``).

    The library and model are loaded lazily on first use, so importing MemoraOS never needs them. Quality on your
    data is NOT measured by the bundled benchmark unless you run it with this embedder.
    """

    provider = "sentence-transformers"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", *, device: str | None = None, batch_size: int = 32, revision: str | None = None, model=None):
        self.model_name = model_name
        self.name = f"st:{model_name}"
        self.device = device
        self.batch_size = batch_size
        self.model_version = revision or ""
        self._model = model
        self._dim: int | None = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ProviderUnavailable("sentence-transformers is not installed; run: pip install sentence-transformers") from exc
            try:
                self._model = SentenceTransformer(self.model_name, device=self.device, revision=self.model_version or None)
            except Exception as exc:  # noqa: BLE001 - download/auth/model errors all mean "unavailable"
                raise ProviderUnavailable(f"could not load {self.model_name}: {exc}") from exc
        return self._model

    @property
    def dim(self) -> int:  # type: ignore[override]
        if self._dim is None:
            self._dim = int(self._load().get_sentence_embedding_dimension())
        return self._dim

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        try:
            vecs = self._load().encode(texts, batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"{self.name}: {exc}") from exc
        arr = np.asarray(vecs, dtype=np.float32)
        self._dim = int(arr.shape[1])
        return arr
