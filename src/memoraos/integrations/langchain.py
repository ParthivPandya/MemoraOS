"""LangChain retriever backed by MemoraOS (``pip install "memoraos[langchain]"``).

Unlike a plain vector retriever it can return nothing: when MemoraOS finds no supporting evidence for a question,
``invoke`` returns an empty list instead of the nearest-looking passages. Every document carries the citation fields
(``memory_id``, ``span_start``, ``span_end``, ``quote_sha256``) that ``MemoryOS.verify_citations`` checks.
"""

from __future__ import annotations

from typing import Any

try:
    from langchain_core.callbacks import CallbackManagerForRetrieverRun
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError('MemoraOSRetriever needs langchain-core: pip install "memoraos[langchain]"') from exc

from ..engine import MemoryOS


class MemoraOSRetriever(BaseRetriever):
    """Retrieve cited evidence for a query from a :class:`MemoryOS` store.

    ``as_of`` answers as the memory stood at that time. ``include_unsupported`` also returns the passages MemoraOS
    declined to answer from (the default drops them, which is the point of the abstention).
    """

    memory: Any
    user_id: str
    tenant_id: str = "default"
    top_k: int = 5
    as_of: str | None = None
    include_unsupported: bool = False

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        mem: MemoryOS = self.memory
        res = mem.recall(query, user_id=self.user_id, tenant_id=self.tenant_id, top_k=self.top_k, as_of=self.as_of)
        if not res.supported and not self.include_unsupported:
            return []
        return [
            Document(
                page_content=ev.excerpt,
                metadata={
                    "memory_id": ev.memory_id, "source_id": ev.source_id, "kind": ev.kind, "score": ev.score,
                    "verification": ev.verification, "source_type": ev.source_type, "effective_at": ev.effective_at,
                    "flags": ev.flags, "span_start": ev.span_start, "span_end": ev.span_end, "quote_sha256": ev.quote_sha256,
                    "recall_id": res.recall_id, "answer": res.answer, "status": res.status,
                },
            )
            for ev in res.evidence[: self.top_k]
        ]
