"""Temporal memory: salary history, current vs. historical answers, time travel, conflicts.

Run:  python examples/temporal_memory/main.py
"""

import sys

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

memory = MemoryOS.in_memory()
u = "user_001"
for sal, year in (("₹28 LPA", 2024), ("₹30 LPA", 2025), ("₹32 LPA", 2026)):
    memory.remember(f"Parth's salary is {sal} in {year}.", user_id=u)

for q in ("What is Parth's current salary?", "What was Parth's salary in 2025?", "Show the history of Parth's salary"):
    r = memory.recall(q, user_id=u)
    print(f"{q}\n  -> {r.answer}   [{r.strategy}, validity={r.confidence.temporal_validity}]")

print("\nTimeline:")
for e in memory.history(subject="Parth", predicate="salary", user_id=u)["timeline"]:
    print(f"  {e['status']:<10} {e['value']:<10} valid_from={e['valid_from']}")

# Version change vs. real conflict
memory.remember("Project Atlas uses Angular 16.", user_id=u, source_type="document")
memory.remember("Project Atlas uses Angular 19.", user_id=u, source_type="document")
memory.remember("The database of Project Atlas is PostgreSQL.", user_id=u, source_type="document")
memory.remember("The database of Project Atlas is MySQL.", user_id=u, source_type="document")
print("\nAngular:", memory.recall("Which Angular version does Atlas use?", user_id=u).answer)
r = memory.recall("Which database does Atlas use?", user_id=u)
print("Database:", r.status, "-", r.answer)
for c in memory.contradictions(user_id=u):
    print(f"  {c.kind}: {c.values} resolved={c.resolved} ({c.justification})")
memory.close()
