"""Quick start: remember, recall with evidence, restart, and unsupported questions.

Run:  python examples/basic_memory/main.py
"""

import sys
import tempfile

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

with tempfile.TemporaryDirectory() as data_dir:
    memory = MemoryOS.local(data_dir)
    memory.remember("The user is building an AI orchestration platform", user_id="user_001")
    memory.remember("Parth's salary is ₹32 LPA.", user_id="user_001", origin="hr-letter")

    result = memory.recall("What AI platform is the user building?", user_id="user_001")
    print("answer  :", result.answer)
    print("strategy:", result.strategy, "| tried:", result.strategies_tried)
    print("evidence:", [(e.memory_id, e.excerpt) for e in result.evidence])

    memory.close()  # simulate an application restart: everything is on disk
    memory = MemoryOS.local(data_dir)
    print("after restart:", memory.recall("What is Parth's exact salary?", user_id="user_001").answer)

    missing = memory.recall("What is Parth's blood group?", user_id="user_001")
    print("unsupported:", missing.status, "-", missing.answer)
    memory.close()
