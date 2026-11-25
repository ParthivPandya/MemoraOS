"""Memory context for an LLM prompt: cited evidence plus recorded failed attempts, as delimited untrusted data.

Shared by the proxy (``memoraos proxy``) and the agent hooks (``memoraos hook``). Nothing here asks the model to
trust the memory: stored text is neutralised so it cannot close or forge the delimiter tags, and the policy line
says it is data, not instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import MemoryOS
from .security import SYSTEM_POLICY, neutralize, redact_secrets, render_untrusted_context

OPEN, CLOSE = "<memoraos_context>", "</memoraos_context>"


@dataclass
class MemoryContext:
    text: str = ""
    evidence: int = 0
    warnings: int = 0
    recall_id: str | None = None
    memory_ids: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.text)


def _warning_line(w: dict) -> str:
    reason = f" Reason: {neutralize(w['reason'])}" if w.get("reason") else ""
    trust = "verified" if w.get("verified") else "unverified"
    return f"- {neutralize(w['action'])} (failed, {trust}, recorded {w['recorded_at'][:10]}, memory {w['memory_id']}).{reason}"


def build_context(
    engine: MemoryOS, query: str, *, user_id: str, tenant_id: str = "default", max_evidence: int = 4, max_warnings: int = 3,
    with_evidence: bool = True,
) -> MemoryContext:
    """Cited evidence for ``query`` (only when MemoraOS can support an answer) and matching failed attempts.

    Returns an empty context when there is nothing to add; a refused recall (``insufficient_evidence``) adds no
    evidence rather than padding the prompt with weak matches.
    """
    query = redact_secrets((query or "").strip())[0]  # the lookup text is written to the recall log
    if not query:
        return MemoryContext()
    warnings = engine.outcome_warnings(query, user_id=user_id, tenant_id=tenant_id, limit=max_warnings)
    evidence = []
    recall_id = None
    if with_evidence:
        res = engine.recall(query, user_id=user_id, tenant_id=tenant_id)
        if res.status != "insufficient_evidence":
            evidence = [e for e in res.evidence if e.kind != "path"][:max_evidence]
            recall_id = res.recall_id
    if not evidence and not warnings:
        return MemoryContext()
    parts = [OPEN, SYSTEM_POLICY]
    if warnings:
        parts.append("Previously recorded failed attempts that match this request (check before repeating them):")
        parts += [_warning_line(w) for w in warnings]
    if evidence:
        parts.append("Stored memory relevant to this request, quoted from what was saved:")
        parts.append(render_untrusted_context(evidence).split("\n", 1)[1])
    parts.append(CLOSE)
    return MemoryContext(
        text="\n".join(parts), evidence=len(evidence), warnings=len(warnings), recall_id=recall_id,
        memory_ids=[e.memory_id for e in evidence] + [w["memory_id"] for w in warnings],
    )
