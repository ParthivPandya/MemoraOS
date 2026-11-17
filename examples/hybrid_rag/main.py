"""Hybrid RAG over documents: chunked ingestion, strategy routing, forced strategies, explain().

Run:  python examples/hybrid_rag/main.py
"""

import sys
import tempfile
from pathlib import Path

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

with tempfile.TemporaryDirectory() as tmp:
    doc = Path(tmp) / "runbook.txt"
    filler = "\n\n".join(f"Section {i}. The platform team reviewed vendor budgets and the holiday schedule. " * 4 for i in range(8))
    doc.write_text(filler + "\n\nOperational note. The rollback window for Orion Gateway is 15 minutes.\n\n" + filler)

    memory = MemoryOS.local(Path(tmp) / "data")
    res = memory.ingest_document(doc, user_id="u1")
    print(f"ingested {len(res.memory_ids)} chunks from one source ({res.source_id})")

    for q in ("What is the rollback window for Orion Gateway?", "Find the Orion Gateway rollback window"):
        for strategy in (None, "bm25", "vector", "hybrid"):
            r = memory.recall(q, user_id="u1", strategy=strategy)
            print(f"{str(strategy or 'auto'):7} -> {r.strategy:7} {r.status:22} {r.answer[:70]!r}")

    r = memory.recall("What is the rollback window for Orion Gateway?", user_id="u1")
    ex = memory.explain(r.recall_id, user_id="u1")
    print("\nrouting reasons:", ex["plan"]["reasons"])
    print("evidence source:", r.evidence[0].source_id, "memory:", r.evidence[0].memory_id)
    memory.close()
