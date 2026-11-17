"""Typed results of an extraction run. Facts themselves stay ``ingestion.extract.ExtractedFact``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ingestion.extract import ExtractedFact

__all__ = ["ExtractedFact", "ExtractionAttempt", "ExtractionResult"]


@dataclass
class ExtractionAttempt:
    """One extractor run on one chunk. Persisted so failures are visible and retryable instead of silent."""

    method: str
    extractor_version: str
    status: str  # ok | skipped | invalid_json | provider_error | partial
    error: str | None = None
    n_proposed: int = 0
    n_accepted: int = 0
    n_rejected: int = 0
    latency_ms: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    facts: list[ExtractedFact] = field(default_factory=list)
    attempts: list[ExtractionAttempt] = field(default_factory=list)
    rejected: list[tuple[ExtractedFact, str]] = field(default_factory=list)

    @property
    def method(self) -> str:
        return "+".join(dict.fromkeys(a.method for a in self.attempts)) or "none"
