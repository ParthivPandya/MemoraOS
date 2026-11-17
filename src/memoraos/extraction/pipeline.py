"""Extractor composition: rules only, LLM with rules fallback, or both merged."""

from __future__ import annotations

from collections.abc import Callable

from ..ingestion.extract import ExtractedFact, norm_entity, norm_object
from ..providers.base import ChatProvider
from .base import MemoryExtractor
from .llm import LLMExtractor
from .rules import RulesExtractor
from .schema import ExtractionAttempt, ExtractionResult
from .values import value_key

_FAILED = {"provider_error", "invalid_json"}


def _identity(f: ExtractedFact) -> tuple:
    return (norm_entity(f.subject), f.predicate, value_key(f.object, f.predicate, f.excerpt) or norm_object(f.object), f.polarity)


def _overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    return bool(a and b and a[0] < b[1] and b[0] < a[1])


class HybridExtractor(MemoryExtractor):
    """Run rules and an LLM; keep every deterministic fact, add only validated LLM facts that rules did not find.

    When both describe the same (subject, predicate) inside overlapping text with different values, the
    deterministic fact wins and the disagreement is recorded in the attempt detail.
    """

    name = "hybrid"

    def __init__(self, rules: RulesExtractor, llm: LLMExtractor):
        self.rules, self.llm = rules, llm
        self.version = f"{rules.version}+{llm.version}"

    def extract(self, text: str, *, default_subject: str = "user") -> ExtractionResult:
        base = self.rules.extract(text, default_subject=default_subject)
        extra = self.llm.extract(text, default_subject=default_subject)
        facts = list(base.facts)
        seen = {_identity(f) for f in facts}
        disagreements: list[dict] = []
        added = 0
        for f in extra.facts:
            if _identity(f) in seen:
                continue
            clash = next(
                (r for r in base.facts if _overlap(r.source_span, f.source_span) and norm_entity(r.subject) == norm_entity(f.subject) and r.predicate == f.predicate),
                None,
            )
            if clash is not None:
                disagreements.append({"rules": clash.object, "llm": f.object, "predicate": f.predicate})
                continue
            facts.append(f)
            seen.add(_identity(f))
            added += 1
        attempts = [*base.attempts, *extra.attempts]
        if disagreements or added:
            attempts.append(ExtractionAttempt("hybrid", self.version, "ok", n_accepted=added, detail={"disagreements": disagreements}))
        return ExtractionResult(facts=facts, attempts=attempts, rejected=extra.rejected)


class FallbackExtractor(MemoryExtractor):
    """LLM first; if the provider fails or returns garbage, fall back to rules so ingestion never loses facts."""

    name = "llm"

    def __init__(self, rules: RulesExtractor, llm: LLMExtractor):
        self.rules, self.llm = rules, llm
        self.version = llm.version

    def extract(self, text: str, *, default_subject: str = "user") -> ExtractionResult:
        res = self.llm.extract(text, default_subject=default_subject)
        if res.attempts and res.attempts[-1].status in _FAILED:
            fb = self.rules.extract(text, default_subject=default_subject)
            fb.attempts[0].status = "fallback"
            return ExtractionResult(facts=fb.facts, attempts=[*res.attempts, *fb.attempts])
        return res


def build_extractor(mode: str, chat: ChatProvider | None = None, *, usage_sink: Callable | None = None, strict: bool = True) -> MemoryExtractor:
    """``rules`` (default, offline) | ``llm`` (LLM with rules fallback) | ``hybrid`` (both merged)."""
    rules = RulesExtractor()
    if mode == "rules":
        return rules
    if mode not in ("llm", "hybrid"):
        raise ValueError("extraction_mode must be 'rules', 'llm' or 'hybrid'")
    if chat is None:
        return rules  # no model configured: stay deterministic rather than fail
    llm = LLMExtractor(chat, strict=strict, usage_sink=usage_sink)
    return HybridExtractor(rules, llm) if mode == "hybrid" else FallbackExtractor(rules, llm)
