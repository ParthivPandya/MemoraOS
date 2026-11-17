"""Research memory on REAL documents: many notes, a connection question, consolidation that keeps the originals, reflection.

Run:  python examples/research_memory/main.py
"""

import sys
from pathlib import Path

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

DOCS = sorted((Path(__file__).resolve().parents[2] / "docs").glob("*.md"))
memory = MemoryOS.in_memory()
u = "researcher"
for path in DOCS:
    memory.remember(path.read_text(encoding="utf-8"), user_id=u, source_type="document", origin=path.name)
print(f"stored {len(DOCS)} real documents -> {memory.stats()['memories']} memories")

r = memory.recall("How is Memorilla related to SlotAttentionMemory?", user_id=u)
print("\nconnection question:", r.strategy, "->", r.status)
print("sources  :", sorted({e.source_id for e in r.evidence})[:3])

report = memory.consolidate(user_id=u)
print(f"\nconsolidation: {len(report['created_memory_ids'])} derived summaries, originals modified = {report['originals_modified']}")
for mid in report["created_memory_ids"][:2]:
    print("  derived:", memory.get(mid, user_id=u).original_content[:110].replace("\n", " "), "...")

print("\nreflect:", [e["entity"] for e in memory.reflect(user_id=u)["recurring_entities"]][:6])
memory.rollback_consolidation(report["run_id"], user_id=u)
print("after rollback, derived memories:", sum(m.derived for m in memory.list_memories(user_id=u, limit=1000)))
memory.close()
