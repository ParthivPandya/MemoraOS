"""Public data models (Pydantic) shared by the engine, API and SDKs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ScopeLevel = Literal["user", "agent", "session", "project", "org"]
Category = Literal["episodic", "semantic", "procedural"]
Verification = Literal["unverified", "verified", "disputed"]
SourceType = Literal[
    "user_statement", "conversation", "document", "structured", "external", "inferred", "consolidation"
]
Status = Literal["answered", "conflict", "insufficient_evidence"]

# Default reliability by source type (documented in docs/MEMORY_DESIGN.md).
SOURCE_RELIABILITY: dict[str, float] = {
    "user_statement": 0.9,
    "structured": 0.85,
    "document": 0.7,
    "conversation": 0.75,
    "external": 0.6,
    "inferred": 0.4,
    "consolidation": 0.3,
}


class Scope(BaseModel):
    """Identity of the requester. Every read and write is filtered through this."""

    tenant_id: str = "default"
    user_id: str
    agent_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None

    @model_validator(mode="after")
    def _nonempty(self) -> Scope:
        if not self.tenant_id.strip() or not self.user_id.strip():
            raise ValueError("tenant_id and user_id must be non-empty")
        return self


class Fact(BaseModel):
    id: str
    memory_id: str
    subject: str
    predicate: str
    object: str
    subject_key: str = ""
    object_key: str = ""
    slot: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    recorded_at: str
    retracted_at: str | None = None
    extraction_confidence: float
    source_reliability: float
    source_id: str | None = None
    source_type: str | None = None
    verification: str = "unverified"
    excerpt: str = ""
    polarity: str = "affirmed"
    extraction_method: str = "rules-v1"
    span_start: int | None = None
    span_end: int | None = None


class Evidence(BaseModel):
    memory_id: str
    source_id: str | None = None
    excerpt: str
    kind: Literal["fact", "passage", "path"] = "passage"
    score: float = 0.0
    source_type: str | None = None
    source_reliability: float | None = None
    verification: str | None = None
    effective_at: str | None = None
    recorded_at: str | None = None
    flags: list[str] = Field(default_factory=list)
    # Citation: where the quote sits in the memory's stored text, and its hash. Check with `MemoryOS.verify_citations`.
    span_start: int | None = None
    span_end: int | None = None
    quote_sha256: str | None = None


class Confidence(BaseModel):
    """Separate signals, deliberately never merged into one number."""

    extraction_confidence: float | None = None
    source_reliability: float | None = None
    temporal_validity: Literal["current", "historical", "conflicted", "undated", "not_applicable"] = "not_applicable"
    retrieval_relevance: float = 0.0
    evidence_coverage: float = 0.0
    route_confidence: float = 0.0


class TimelineEntry(BaseModel):
    value: str
    valid_from: str | None
    valid_until: str | None
    recorded_at: str
    status: Literal["current", "historical", "conflicted"]
    memory_ids: list[str]
    source_reliability: float
    inferred_start: bool = False
    note: str | None = None


class Contradiction(BaseModel):
    subject: str
    slot: str
    values: list[str]
    kind: Literal["conflict", "update", "possible_version_change", "resolved_by_reliability"]
    resolved: bool
    justification: str
    memory_ids: list[str]
    since: str | None = None


class RoutePlan(BaseModel):
    category: str
    primary: str
    stages: list[str]
    fallbacks: list[str]
    scores: dict[str, float]
    features: dict[str, Any]
    reasons: list[str]
    route_confidence: float
    estimated_cost: float
    learned_override: bool = False


class RecallResult(BaseModel):
    recall_id: str
    query: str
    answer: str
    status: Status
    supported: bool
    strategy: str
    strategies_tried: list[str]
    fallback_used: bool
    evidence: list[Evidence]
    timeline: list[TimelineEntry] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    confidence: Confidence
    plan: RoutePlan
    flags: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    context_tokens: int = 0
    as_of: str | None = None
    cached: bool = False

    def render_context(self) -> str:
        """Evidence formatted as delimited, untrusted data suitable for an LLM prompt."""
        from .security import render_untrusted_context

        return render_untrusted_context(self.evidence)


class MemoryRecord(BaseModel):
    id: str
    source_id: str
    original_content: str
    normalized_content: str
    category: str
    scope_level: str
    user_id: str
    created_at: str
    effective_at: str | None
    updated_at: str
    version: int
    confidence: float
    source_type: str
    source_reliability: float
    verification: str
    derived: bool = False
    mention_count: int = 1
    importance: float = 0.0
    duplicate_of: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RememberResult(BaseModel):
    memory_ids: list[str]
    source_id: str
    duplicate_of: str | None = None
    facts_recorded: int = 0
    conflicts: list[Contradiction] = Field(default_factory=list)
    redactions: int = 0
