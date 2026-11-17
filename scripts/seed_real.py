"""Seed a running MemoraOS API with REAL data only (nothing invented).

    python scripts/seed_real.py http://127.0.0.1:8000 <api-key> [user_id]

1. Every heading section of the project's own documentation is stored through the public REST client as a `document`
   memory with its file and heading as `origin`.
2. The dated CPython release history (`data/python_releases.json`, copied from PEP 693/719/745) is stored as
   structured facts with their real valid-from dates, so the History page shows a real timeline.
3. The questions of `benchmarks/real_docs.py` are asked and feedback is recorded from the mechanical judge (the answer
   contains the verified gold string, or an unanswerable question was refused); the Python questions are asked too.

Used for the dashboard screenshots.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from benchmarks import real_docs
from memoraos.client import MemoraClient

PYTHON_QUESTIONS = [  # (question, gold) with gold read off the PEP release dates in data/python_releases.json
    ("What is the latest version of Python 3.14?", "3.14.10"),
    ("What was the latest version of Python 3.14 in March 2026?", "3.14.3"),
    ("What was the previous latest version of Python 3.14?", "3.14.9"),
    ("What was the latest stable version of Python before October 2024?", "3.12"),
]


def main() -> None:
    base, key = sys.argv[1], sys.argv[2]
    user = sys.argv[3] if len(sys.argv) > 3 else "user_001"
    c = MemoraClient(base, key, user_id=user)
    scenario, origin, _sha = real_docs.build()
    for ev in scenario.events:
        c.remember(ev.text, source_type="document", origin=origin[ev.idx])
    data = json.loads((Path(__file__).resolve().parents[1] / "data" / "python_releases.json").read_text(encoding="utf-8"))
    for rec in data["records"]:
        c.remember_json({k: rec[k] for k in ("subject", "predicate", "object", "valid_from")}, origin=rec["source"])
    correct = 0
    for q in scenario.questions:
        r = c.recall(q.text)
        ok = (not r["supported"]) if not q.answerable else (r["supported"] and all(g.lower() in r["answer"].lower() for g in q.gold))
        correct += bool(ok)
        c.feedback(r["recall_id"], correct=bool(ok))
    for q, gold in PYTHON_QUESTIONS:
        r = c.recall(q)
        c.feedback(r["recall_id"], correct=bool(r["supported"] and gold in r["answer"]))
    c.consolidate()
    st = c.stats()
    print(f"seeded {len(scenario.events)} doc sections + {len(data['records'])} dated facts; asked {len(scenario.questions) + len(PYTHON_QUESTIONS)} questions ({correct}/{len(scenario.questions)} judged correct); recalls={st['recalls']}")


if __name__ == "__main__":
    main()
