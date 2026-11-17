"""Quick start on REAL text: remember MemoraOS's own architecture decision records, ask questions with evidence,
restart, and see an unsupported question refused.

Run:  python examples/basic_memory/main.py
"""

import sys
import tempfile
from pathlib import Path

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

ADRS = sorted((Path(__file__).resolve().parents[2] / "docs" / "ADR").glob("*.md"))

with tempfile.TemporaryDirectory() as data_dir:
    memory = MemoryOS.local(data_dir)
    for path in ADRS:
        memory.remember(path.read_text(encoding="utf-8"), user_id="me", source_type="document", origin=path.name)
    print(f"stored {len(ADRS)} real documents -> {memory.stats()['memories']} memories")

    result = memory.recall("Why did the Windows CI test fail intermittently?", user_id="me")
    print("\nanswer  :", result.answer)
    print("strategy:", result.strategy, "| tried:", result.strategies_tried)
    print("evidence:", [(e.memory_id, e.source_type, e.excerpt[:60] + "...") for e in result.evidence[:1]])

    memory.close()  # simulate an application restart: everything is on disk
    memory = MemoryOS.local(data_dir)
    after = memory.recall("What is the name of the exception raised when a model name is reused with a different dimension?", user_id="me")
    print("\nafter restart:", after.status, "-", after.answer[:140])

    missing = memory.recall("What is the monthly price of the hosted MemoraOS plan?", user_id="me")
    print("\nunsupported:", missing.status, "-", missing.answer)
    memory.close()
