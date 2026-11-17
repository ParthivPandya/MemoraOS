"""Provider interfaces. MemoraOS never depends on a specific model vendor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


class ProviderError(RuntimeError):
    """A provider failed after retries (network, auth, malformed response)."""


class ProviderUnavailable(ProviderError):
    """The provider cannot be reached or the requested model is missing."""


@dataclass
class Usage:
    provider: str
    model: str
    kind: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0


@dataclass
class ChatResponse:
    text: str
    usage: Usage


@dataclass
class ExtractedEntities:
    entities: list[str] = field(default_factory=list)
    relations: list[tuple[str, str, str]] = field(default_factory=list)


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) float32 matrix of L2-normalised vectors."""
        ...


@runtime_checkable
class ChatProvider(Protocol):
    name: str

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 512) -> ChatResponse: ...


@runtime_checkable
class RerankProvider(Protocol):
    name: str

    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


@runtime_checkable
class EntityExtractor(Protocol):
    name: str

    def extract(self, text: str) -> ExtractedEntities: ...
