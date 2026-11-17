"""SQLite connection management, versioned migrations, transactions and backup."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Each entry is applied exactly once, in order, inside a transaction. Never edit an applied
# migration; append a new one.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
CREATE TABLE sources(
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, scope_level TEXT NOT NULL, scope_id TEXT NOT NULL,
    source_type TEXT NOT NULL, origin TEXT, content TEXT NOT NULL, content_hash TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}', file_path TEXT,
    reliability REAL NOT NULL, verification TEXT NOT NULL DEFAULT 'unverified',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_sources_tenant ON sources(tenant_id, user_id);

CREATE TABLE memories(
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, scope_level TEXT NOT NULL, scope_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id),
    chunk_index INTEGER NOT NULL DEFAULT 0,
    original_content TEXT NOT NULL, normalized_content TEXT NOT NULL, content_hash TEXT NOT NULL,
    category TEXT NOT NULL, confidence REAL NOT NULL,
    created_at TEXT NOT NULL, effective_at TEXT, updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    derived INTEGER NOT NULL DEFAULT 0,
    importance REAL NOT NULL DEFAULT 0, access_count INTEGER NOT NULL DEFAULT 0,
    mention_count INTEGER NOT NULL DEFAULT 1,
    duplicate_of TEXT,
    embedding_hash TEXT, embedding_model TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_mem_scope ON memories(tenant_id, scope_level, scope_id, status);
CREATE INDEX idx_mem_user ON memories(tenant_id, user_id, status);
CREATE INDEX idx_mem_hash ON memories(tenant_id, scope_level, scope_id, content_hash);
CREATE INDEX idx_mem_created ON memories(created_at);

CREATE TABLE memory_versions(
    memory_id TEXT NOT NULL, version INTEGER NOT NULL,
    original_content TEXT NOT NULL, normalized_content TEXT NOT NULL,
    changed_at TEXT NOT NULL, reason TEXT, actor TEXT,
    PRIMARY KEY(memory_id, version)
);

CREATE TABLE memory_provenance(
    memory_id TEXT NOT NULL, source_id TEXT NOT NULL, seen_at TEXT NOT NULL,
    PRIMARY KEY(memory_id, source_id)
);

CREATE TABLE embeddings(
    content_hash TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL,
    PRIMARY KEY(content_hash, model)
);

CREATE VIRTUAL TABLE memories_fts USING fts5(content, tokenize='porter unicode61');

CREATE TABLE facts(
    id TEXT PRIMARY KEY, memory_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, scope_level TEXT NOT NULL, scope_id TEXT NOT NULL,
    subject TEXT NOT NULL, subject_key TEXT NOT NULL,
    predicate TEXT NOT NULL, object TEXT NOT NULL, object_key TEXT NOT NULL, slot TEXT,
    valid_from TEXT, valid_until TEXT, date_precision TEXT,
    recorded_at TEXT NOT NULL, retracted_at TEXT,
    extraction_confidence REAL NOT NULL, source_reliability REAL NOT NULL,
    excerpt TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_facts_slot ON facts(tenant_id, subject_key, predicate);
CREATE INDEX idx_facts_pred ON facts(tenant_id, predicate);
CREATE INDEX idx_facts_memory ON facts(memory_id);

CREATE TABLE mentions(
    memory_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, scope_level TEXT NOT NULL, scope_id TEXT NOT NULL,
    entity_key TEXT NOT NULL, entity_name TEXT NOT NULL,
    PRIMARY KEY(memory_id, entity_key)
);
CREATE INDEX idx_mentions_entity ON mentions(tenant_id, entity_key);

CREATE TABLE aliases(
    alias_key TEXT NOT NULL, canonical_key TEXT NOT NULL, run_id TEXT,
    tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, scope_level TEXT NOT NULL, scope_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
    PRIMARY KEY(tenant_id, scope_level, scope_id, alias_key)
);

CREATE TABLE memory_links(
    src_id TEXT NOT NULL, dst_id TEXT NOT NULL, type TEXT NOT NULL, run_id TEXT,
    tenant_id TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(src_id, dst_id, type)
);
CREATE INDEX idx_links_dst ON memory_links(dst_id);

CREATE TABLE events(
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, tenant_id TEXT NOT NULL, actor TEXT, type TEXT NOT NULL,
    memory_id TEXT, payload TEXT NOT NULL DEFAULT '{}',
    prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE INDEX idx_events_mem ON events(memory_id);

CREATE TABLE audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, tenant_id TEXT NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT
);

CREATE TABLE retrieval_log(
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
    query TEXT NOT NULL, category TEXT NOT NULL, strategy TEXT NOT NULL,
    strategies_tried TEXT NOT NULL, fallback_used INTEGER NOT NULL,
    status TEXT NOT NULL, supported INTEGER NOT NULL, answer TEXT,
    latency_ms REAL NOT NULL, context_tokens INTEGER NOT NULL, cost REAL NOT NULL DEFAULT 0,
    cached INTEGER NOT NULL DEFAULT 0,
    plan TEXT NOT NULL, explanation TEXT NOT NULL, evidence_ids TEXT NOT NULL, as_of TEXT
);
CREATE INDEX idx_retlog_tenant ON retrieval_log(tenant_id, ts);

CREATE TABLE feedback(
    id INTEGER PRIMARY KEY AUTOINCREMENT, recall_id TEXT NOT NULL, ts TEXT NOT NULL,
    correct INTEGER, relevance REAL, comment TEXT
);
CREATE INDEX idx_feedback_recall ON feedback(recall_id);

CREATE TABLE consolidation_runs(
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
    mode TEXT NOT NULL, status TEXT NOT NULL, watermark INTEGER NOT NULL DEFAULT 0,
    report TEXT NOT NULL, rolled_back_at TEXT
);

CREATE TABLE provider_usage(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, provider TEXT NOT NULL, model TEXT,
    kind TEXT NOT NULL, tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0, latency_ms REAL NOT NULL DEFAULT 0
);
""",
    ),
    (
        2,
        # Additive only: v0.1 rows keep working and get explicit, honest defaults.
        """
ALTER TABLE facts ADD COLUMN polarity TEXT NOT NULL DEFAULT 'affirmed';
ALTER TABLE facts ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'rules-v1';
ALTER TABLE facts ADD COLUMN extractor_version TEXT NOT NULL DEFAULT '';
ALTER TABLE facts ADD COLUMN source_span_start INTEGER;
ALTER TABLE facts ADD COLUMN source_span_end INTEGER;
ALTER TABLE facts ADD COLUMN value_num REAL;
ALTER TABLE facts ADD COLUMN value_unit TEXT;
ALTER TABLE facts ADD COLUMN value_currency TEXT;
CREATE INDEX idx_facts_value ON facts(tenant_id, predicate, object_key);

ALTER TABLE embeddings ADD COLUMN provider TEXT NOT NULL DEFAULT '';
ALTER TABLE embeddings ADD COLUMN model_version TEXT NOT NULL DEFAULT '';
ALTER TABLE embeddings ADD COLUMN normalization TEXT NOT NULL DEFAULT 'l2';
ALTER TABLE embeddings ADD COLUMN created_at TEXT NOT NULL DEFAULT '';
ALTER TABLE embeddings ADD COLUMN status TEXT NOT NULL DEFAULT 'ready';
CREATE INDEX idx_embeddings_model ON embeddings(model, status);

CREATE TABLE embedding_models(
    model TEXT PRIMARY KEY, provider TEXT NOT NULL, model_version TEXT NOT NULL DEFAULT '',
    dim INTEGER NOT NULL, normalization TEXT NOT NULL DEFAULT 'l2',
    first_seen_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE extraction_attempts(
    id TEXT PRIMARY KEY, memory_id TEXT, tenant_id TEXT NOT NULL, ts TEXT NOT NULL,
    method TEXT NOT NULL, extractor_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL, error TEXT, n_proposed INTEGER NOT NULL DEFAULT 0,
    n_accepted INTEGER NOT NULL DEFAULT 0, n_rejected INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_extract_attempts_mem ON extraction_attempts(memory_id);
CREATE INDEX idx_extract_attempts_status ON extraction_attempts(tenant_id, status);
""",
    ),
]


class Database:
    """Thread-safe wrapper around one SQLite connection (WAL, foreign keys, busy timeout)."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self._tx_depth = 0
        self.migrate()

    def migrate(self) -> list[int]:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
            pending = [v for v, _ in MIGRATIONS if v not in done]
            if done and pending and self.path != ":memory:":
                self._pre_migration_backup(max(done))
            applied = []
            for version, sql in MIGRATIONS:
                if version in done:
                    continue
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_statements(sql):
                        self._conn.execute(stmt)
                    self._conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES(?, datetime('now'))", (version,)
                    )
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
                applied.append(version)
            return applied

    def _pre_migration_backup(self, from_version: int) -> None:
        """Keep a restorable copy of an existing database before upgrading its schema."""
        target = Path(f"{self.path}.bak-v{from_version}")
        if target.exists():
            return
        self._conn.execute("PRAGMA wal_checkpoint(FULL)")
        dst = sqlite3.connect(str(target))
        try:
            self._conn.backup(dst)
        finally:
            dst.close()

    @property
    def schema_version(self) -> int:
        return int(self._conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Atomic transaction; nested use joins the outer transaction."""
        with self._lock:
            outer = self._tx_depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._tx_depth += 1
            try:
                yield self._conn
            except BaseException:
                self._tx_depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._tx_depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def backup(self, dest: str | Path) -> Path:
        """Consistent online backup using SQLite's backup API."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self._conn.backup(target)
            finally:
                target.close()
        return dest

    def store_version(self) -> int:
        """Monotonic marker that changes whenever any event is appended (used for cache validity)."""
        row = self.one("SELECT COALESCE(MAX(seq), 0) FROM events")
        return int(row[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _split_statements(script: str) -> list[str]:
    """Split a migration script on semicolons that end a statement (no triggers used)."""
    return [s.strip() for s in script.split(";\n") if s.strip()]
