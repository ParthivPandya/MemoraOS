"""Extractor contract. Implementations propose facts; they never write to the database themselves."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..ingestion.dates import DateSpan, extract_dates
from ..ingestion.extract import ExtractedFact, extract_entities, norm_predicate
from ..ingestion.lexicon import RELATIONAL_PREDICATES
from .schema import ExtractionResult
from .validate import validate_fact


class MemoryExtractor(ABC):
    name: str = "extractor"
    version: str = "0"

    @abstractmethod
    def extract(self, text: str, *, default_subject: str = "user") -> ExtractionResult:
        """Return validated facts for ``text`` plus a log of what was attempted."""

    def extract_entities(self, text: str, facts: list[ExtractedFact] | None = None) -> dict[str, str]:
        return extract_entities(text, facts)

    def extract_relationships(self, text: str, facts: list[ExtractedFact] | None = None) -> list[tuple[str, str, str]]:
        facts = facts if facts is not None else self.extract(text).facts
        return [(f.subject, f.predicate, f.object) for f in facts if f.polarity == "affirmed" and f.predicate in RELATIONAL_PREDICATES]

    def extract_temporal_information(self, text: str) -> DateSpan:
        return extract_dates(text)

    def normalize_facts(self, facts: list[ExtractedFact]) -> list[ExtractedFact]:
        for f in facts:
            f.predicate = norm_predicate(f.predicate)
        return facts

    def validate_extraction(self, text: str, facts: list[ExtractedFact], *, strict: bool = True) -> tuple[list[ExtractedFact], list[tuple[ExtractedFact, str]]]:
        accepted: list[ExtractedFact] = []
        rejected: list[tuple[ExtractedFact, str]] = []
        for f in facts:
            reason = validate_fact(f, text, strict=strict)
            (rejected.append((f, reason)) if reason else accepted.append(f))
        return accepted, rejected
