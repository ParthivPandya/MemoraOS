"""The deterministic extractor: no model, no network, same output every time."""

from __future__ import annotations

import time

from ..ingestion.extract import extract_facts
from .base import MemoryExtractor
from .schema import ExtractionAttempt, ExtractionResult

RULES_VERSION = "rules-2.0"


class RulesExtractor(MemoryExtractor):
    name = "rules"
    version = RULES_VERSION

    def extract(self, text: str, *, default_subject: str = "user") -> ExtractionResult:
        t0 = time.perf_counter()
        facts = extract_facts(text, default_subject=default_subject)
        for f in facts:
            f.method, f.extractor_version = "rules-v2", RULES_VERSION
        attempt = ExtractionAttempt(
            method="rules", extractor_version=RULES_VERSION, status="ok", n_proposed=len(facts), n_accepted=len(facts),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        return ExtractionResult(facts=facts, attempts=[attempt])
