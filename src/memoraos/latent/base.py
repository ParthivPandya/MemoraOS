"""Experimental latent semantic memory interfaces.

IMPORTANT: nothing here reproduces Stanford's Memorilla. Memorilla trains a cross-attention memory
module that emits query-conditioned soft tokens into a frozen decoder LLM (arXiv 2610.21375,
https://github.com/snap-stanford/memorilla). This package only defines the integration contract and
ships one CPU baseline (``SlotAttentionMemory``) whose slots are fitted by k-means, not trained
end-to-end. See docs/LATENT_MEMORY.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


class LatentMemoryUnavailable(RuntimeError):
    """A requested latent backend needs models, hardware or packages that are not present."""


@dataclass
class LatentStats:
    n_documents: int
    n_slots: int
    dim: int
    compression_ratio: float
    backend: str


class LatentMemoryBackend(ABC):
    """Contract for a fixed-size latent memory built from document embeddings.

    Implementations must keep a mapping back to the source documents so that evidence stays
    recoverable: the latent state is a retrieval aid, never the only copy of a fact.
    """

    name: str

    @abstractmethod
    def fit(self, doc_ids: list[str], embeddings: np.ndarray) -> None: ...

    @abstractmethod
    def readout(self, query: np.ndarray) -> np.ndarray:
        """Query-conditioned fixed-size representation, shape (n_slots, dim)."""

    @abstractmethod
    def retrieve(self, query: np.ndarray, k: int) -> list[tuple[str, float]]:
        """Source documents most responsible for the readout, as (doc_id, score)."""

    @abstractmethod
    def stats(self) -> LatentStats: ...


class LatentMemoryModel(ABC):
    """Contract for a *learned* model (e.g. a Memorilla checkpoint) that can be plugged in later."""

    @abstractmethod
    def encode_documents(self, texts: list[str]) -> np.ndarray: ...

    @abstractmethod
    def memory_tokens(self, query: str) -> np.ndarray:
        """Soft memory tokens for a decoder; shape (n_tokens, decoder_dim)."""


def memorilla_available() -> bool:
    """True only if a ``memorilla`` Python package is importable. No adapter is claimed beyond that."""
    try:
        import importlib.util

        return importlib.util.find_spec("memorilla") is not None
    except (ImportError, ValueError):
        return False
