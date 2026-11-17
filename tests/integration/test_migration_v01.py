"""Schema migration 2 against a REAL database produced by the v0.1 engine (tests/fixtures/v01.db)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memoraos import MemoryOS
from tests.conftest import FakeClock

FIXTURES = Path(__file__).parent.parent / "fixtures"
U = "user_001"
# v0.1 answered this one with a muddled multi-fact string; v0.2 is allowed (and expected) to do better.
V01_KNOWN_WEAK = {"Which Angular version does Atlas use?"}


def _clock() -> FakeClock:
    # continue just after the fixture's own timeline (it was built in early 2025)
    return FakeClock(datetime(2025, 6, 1, tzinfo=timezone.utc))


@pytest.fixture
def expected() -> dict:
    return json.loads((FIXTURES / "v01_expected.json").read_text(encoding="utf-8"))


@pytest.fixture
def v01_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(FIXTURES / "v01.db", d / "memoraos.db")
    return d


def test_the_committed_fixture_really_is_a_v01_database():
    con = sqlite3.connect(FIXTURES / "v01.db")
    versions = [r[0] for r in con.execute("SELECT version FROM schema_migrations")]
    cols = {r[1] for r in con.execute("PRAGMA table_info(facts)")}
    con.close()
    assert versions == [1]
    assert "polarity" not in cols and "extraction_method" not in cols


def test_upgrade_preserves_every_row_and_the_audit_chain(v01_dir, expected):
    m = MemoryOS.local(v01_dir, clock=_clock())
    try:
        assert m.db.schema_version >= 2
        stats = m.stats()
        assert stats["memories"] == expected["memories"]
        assert stats["sources"] == expected["sources"]
        assert stats["facts"] == expected["facts"]
        assert m.db.one("SELECT COUNT(*) FROM events")[0] == expected["events"]
        assert m.db.one("SELECT COUNT(*) FROM embeddings")[0] == expected["embeddings"]
        assert m.db.one("SELECT COUNT(*) FROM retrieval_log")[0] == expected["retrieval_log"]
        assert m.verify_audit_chain() is True
    finally:
        m.close()


def test_legacy_rows_get_honest_defaults(v01_dir):
    m = MemoryOS.local(v01_dir, clock=_clock())
    try:
        rows = m.db.query("SELECT polarity, extraction_method, source_span_start, value_num FROM facts")
        assert rows
        assert {r["polarity"] for r in rows} == {"affirmed"}
        assert {r["extraction_method"] for r in rows} == {"rules-v1"}
        assert all(r["source_span_start"] is None and r["value_num"] is None for r in rows)
        emb = m.db.query("SELECT status, provider FROM embeddings")
        assert {r["status"] for r in emb} == {"ready"} and {r["provider"] for r in emb} == {""}
        assert m.db.one("SELECT COUNT(*) FROM extraction_attempts")[0] == 0
    finally:
        m.close()


def test_upgraded_database_answers_like_v01(v01_dir, expected):
    m = MemoryOS.local(v01_dir, clock=_clock())
    try:
        for q, answer in expected["answers"].items():
            if q in V01_KNOWN_WEAK:
                continue
            assert m.recall(q, user_id=U, use_cache=False).answer == answer, q
        assert m.recall("How is Alice related to West Europe?", user_id=U, use_cache=False).strategy == expected["graph_strategy"]
        assert m.recall("Which database does Atlas use?", user_id=U, use_cache=False).status == expected["database_status"]
        assert m.recall("What is Parth's current salary?", user_id="user_002", use_cache=False).status == expected["bob_status_for_parth_salary"]
    finally:
        m.close()


def test_upgraded_database_accepts_new_writes_and_keeps_the_chain(v01_dir):
    m = MemoryOS.local(v01_dir, clock=_clock())
    try:
        m.remember("Carol leads Project Zeta.", user_id=U)
        assert "Carol" in m.recall("Who leads Project Zeta?", user_id=U, use_cache=False).answer
        assert m.verify_audit_chain() is True
    finally:
        m.close()


def test_a_restorable_backup_is_taken_and_migration_is_idempotent(v01_dir):
    MemoryOS.local(v01_dir, clock=_clock()).close()
    backup = v01_dir / "memoraos.db.bak-v1"
    assert backup.exists()
    con = sqlite3.connect(backup)
    assert [r[0] for r in con.execute("SELECT version FROM schema_migrations")] == [1]
    con.close()
    m = MemoryOS.local(v01_dir, clock=_clock())
    try:
        assert m.db.migrate() == []
    finally:
        m.close()


def test_fresh_database_creates_the_v2_schema_without_a_backup(tmp_path):
    m = MemoryOS.local(tmp_path / "fresh", clock=_clock())
    try:
        assert m.db.schema_version >= 2
        assert not list((tmp_path / "fresh").glob("*.bak-*"))
    finally:
        m.close()
