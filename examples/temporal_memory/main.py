"""Temporal memory on REAL data: the dated release history of CPython, copied from PEP 693, PEP 719 and PEP 745
(data/python_releases.json). Current vs. past values, "previous", full history, and as-of reasoning.

Run:  python examples/temporal_memory/main.py
"""

import json
import sys
from pathlib import Path

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

data = json.loads((Path(__file__).resolve().parents[2] / "data" / "python_releases.json").read_text(encoding="utf-8"))
memory = MemoryOS.in_memory()
u = "me"
for rec in data["records"]:
    memory.remember_json({k: rec[k] for k in ("subject", "predicate", "object", "valid_from")}, user_id=u, origin=rec["source"])
print(f"stored {len(data['records'])} dated release facts from {', '.join(data['sources'].values())}\n")

for q in (
    "What is the latest version of Python 3.14?",
    "What was the latest version of Python 3.14 in March 2026?",
    "What was the previous latest version of Python 3.14?",
    "What is the latest stable version of Python?",
    "What was the latest stable version of Python before October 2024?",
    "Show the history of the latest version of Python 3.14",
):
    r = memory.recall(q, user_id=u)
    print(f"{q}\n  -> {r.answer}   [{r.strategy}, validity={r.confidence.temporal_validity}]")

print("\nTimeline (last 4 of Python 3.14):")
for e in memory.history(subject="Python 3.14", predicate="latest version", user_id=u)["timeline"][-4:]:
    print(f"  {e['status']:<10} {e['value']:<8} valid_from={e['valid_from']}")
print("\ncontradictions:", memory.contradictions(user_id=u) or "none (each release supersedes the previous one in order)")
memory.close()
