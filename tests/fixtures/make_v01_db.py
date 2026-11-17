"""Generate tests/fixtures/v01.db with the REAL v0.1 engine (schema migration 1 only).

This script was run ONCE, before migration 2 existed, and its output is committed. Re-running it with a newer
engine would produce a newer schema and defeat the purpose of the fixture, so the migration test asserts
that the committed file really is at schema version 1 (see tests/integration/test_migration_v01.py).

    python tests/fixtures/make_v01_db.py   # only on a v0.1 checkout (e.g. git checkout v0.1.0)
"""

from __future__ import annotations

import itertools
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memoraos import MemoryOS

HERE = Path(__file__).parent
OUT = HERE / "v01.db"
EXPECTED = HERE / "v01_expected.json"

base = datetime(2025, 1, 1, tzinfo=timezone.utc)
tick = itertools.count(1)


def clock() -> datetime:
    return base + timedelta(seconds=next(tick))


ids = itertools.count(1)
tmp = HERE / "_tmp_v01"
if OUT.exists():
    OUT.unlink()
m = MemoryOS.local(tmp, clock=clock, id_factory=lambda p: f"{p}_{next(ids):05d}")
U = "user_001"
m.remember("The user is building an AI orchestration platform", user_id=U)
m.remember("Parth's salary is ₹28 LPA in 2024.", user_id=U)
m.remember("Parth's salary is ₹30 LPA in 2025.", user_id=U)
m.remember("Parth's salary is ₹32 LPA in 2026.", user_id=U)
m.remember("Alice leads Project Atlas.", user_id=U, source_type="document", origin="doc-1")
m.remember("Project Atlas uses Azure Functions.", user_id=U, source_type="document", origin="doc-2")
m.remember("Azure Functions is hosted in West Europe.", user_id=U, source_type="document", origin="doc-3")
m.remember("Project Atlas uses Angular 16.", user_id=U, source_type="document")
m.remember("Project Atlas uses Angular 19.", user_id=U, source_type="document")
m.remember("The database of Project Atlas is PostgreSQL.", user_id=U, source_type="document")
m.remember("The database of Project Atlas is MySQL.", user_id=U, source_type="document")
mid = m.remember("The project deadline is 2026-03-01.", user_id=U).memory_ids[0]
m.correct(mid, "The project deadline is 2026-04-15.", user_id=U, reason="client moved it")
m.remember("To deploy Project Atlas: 1. Run `make build`. 2. Run `make release`.", user_id=U)
for i in range(4):
    m.remember(f"Azure architecture note {i}: hub and spoke networking and governance.", user_id=U, source_type="conversation")
m.remember("Bob's salary is ₹10 LPA.", user_id="user_002")
m.remember("Org wide: the release process uses trunk based development.", user_id=U, level="org")
m.consolidate(user_id=U)
res = m.recall("What is Parth's current salary?", user_id=U)
m.feedback(res.recall_id, correct=True)
m.recall("Which database does Atlas use?", user_id=U)
m.recall("What is Parth's blood group?", user_id=U)


def ask(q: str, user: str = U):
    return m.recall(q, user_id=user, use_cache=False)


answers = {
    "What is Parth's current salary?": ask("What is Parth's current salary?").answer,
    "What was Parth's salary in 2025?": ask("What was Parth's salary in 2025?").answer,
    "Which Angular version does Atlas use?": ask("Which Angular version does Atlas use?").answer,
    "What is the project deadline?": ask("What is the project deadline?").answer,
}
graph_strategy = ask("How is Alice related to West Europe?").strategy
database_status = ask("Which database does Atlas use?").status
bob_status = ask("What is Parth's current salary?", "user_002").status

# Row counts are taken AFTER the probing recalls above, because recall writes to retrieval_log.
expected = {
    "memories": m.stats()["memories"],
    "sources": m.stats()["sources"],
    "facts": m.stats()["facts"],
    "derived": m.stats()["derived_memories"],
    "events": m.db.one("SELECT COUNT(*) FROM events")[0],
    "retrieval_log": m.db.one("SELECT COUNT(*) FROM retrieval_log")[0],
    "embeddings": m.db.one("SELECT COUNT(*) FROM embeddings")[0],
    "schema_version": m.db.schema_version,
    "audit_chain_valid": m.verify_audit_chain(),
    "answers": answers,
    "graph_strategy": graph_strategy,
    "database_status": database_status,
    "bob_status_for_parth_salary": bob_status,
}
m.backup(OUT)
m.close()
shutil.rmtree(tmp, ignore_errors=True)
con = sqlite3.connect(OUT)
con.execute("PRAGMA journal_mode=DELETE")
con.close()
EXPECTED.write_text(json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
print(json.dumps(expected, indent=2, ensure_ascii=False))
