"""Hybrid RAG over one real long document (docs/SECURITY.md): chunked ingestion, routing, forced strategies, explain().

Run:  python examples/hybrid_rag/main.py
"""

import sys
import tempfile
from pathlib import Path

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

DOC = Path(__file__).resolve().parents[2] / "docs" / "SECURITY.md"

with tempfile.TemporaryDirectory() as tmp:
    memory = MemoryOS.local(Path(tmp) / "data")
    res = memory.ingest_document(DOC, user_id="me")
    print(f"ingested {DOC.name} ({DOC.stat().st_size:,} bytes) as {len(res.memory_ids)} chunks from one source ({res.source_id})\n")

    for q in ("Which address does the REST API bind to by default?", "Find the SQLCipher roadmap item"):
        for strategy in (None, "bm25", "vector", "hybrid"):
            r = memory.recall(q, user_id="me", strategy=strategy)
            print(f"{str(strategy or 'auto'):7} -> {r.strategy:7} {r.status:22} {r.answer[:78]!r}")
        print()

    r = memory.recall("Which address does the REST API bind to by default?", user_id="me")
    ex = memory.explain(r.recall_id, user_id="me")
    print("routing reasons:", ex["plan"]["reasons"])
    print("evidence source:", r.evidence[0].source_id, "memory:", r.evidence[0].memory_id)
    memory.close()
