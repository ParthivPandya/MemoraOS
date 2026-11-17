"""Memory extraction: deterministic rules, validated LLM proposals, and value normalisation.

Submodules are imported lazily so that low-level modules (``ingestion.extract``) can use ``extraction.values``
without an import cycle.
"""

from __future__ import annotations

import importlib

_EXPORTS = {
    "parse_value": "values", "value_key": "values", "ParsedValue": "values",
    "MemoryExtractor": "base", "RulesExtractor": "rules", "LLMExtractor": "llm", "HybridExtractor": "pipeline",
    "ExtractionResult": "schema", "ExtractionAttempt": "schema", "build_extractor": "pipeline", "FallbackExtractor": "pipeline",
    "validate_fact": "validate", "GroundingError": "validate",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        return getattr(importlib.import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(name)
