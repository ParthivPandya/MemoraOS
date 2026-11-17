"""Research memory: many notes, graph questions, consolidation that keeps the originals, reflection.

Run:  python examples/research_memory/main.py
"""

import sys

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

memory = MemoryOS.in_memory()
u = "researcher"
papers = [
    "Alice leads Project Atlas.",
    "Project Atlas uses Azure Functions.",
    "Azure Functions depends on Cosmos DB.",
    "Cosmos DB is hosted in Central India.",
]
for i, p in enumerate(papers):
    memory.remember(p, user_id=u, source_type="document", origin=f"paper-{i}")
for i in range(4):
    memory.remember(f"Reading note {i}: Azure architecture needs hub and spoke networking and cost governance.", user_id=u, source_type="conversation")

r = memory.recall("How is Alice related to Central India?", user_id=u)
print("multi-hop:", r.strategy, "->", r.answer)
print("sources  :", sorted({e.source_id for e in r.evidence}))

report = memory.consolidate(user_id=u)
print(f"\nconsolidation: {len(report['created_memory_ids'])} derived summaries, originals modified = {report['originals_modified']}")
for mid in report["created_memory_ids"]:
    print("  derived:", memory.get(mid, user_id=u).original_content[:110], "...")

print("\nreflect:", [e["entity"] for e in memory.reflect(user_id=u)["recurring_entities"]][:5])
memory.rollback_consolidation(report["run_id"], user_id=u)
print("after rollback, derived memories:", sum(m.derived for m in memory.list_memories(user_id=u)))
memory.close()
