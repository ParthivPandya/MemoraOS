"""Low-level persistence operations shared by ingestion, correction, deletion and consolidation."""

from __future__ import annotations

import json
import sqlite3
import threading
import unicodedata
from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np

from .config import Settings
from .extraction.schema import ExtractionAttempt
from .extraction.values import parse_value
from .ingestion.extract import ExtractedFact, norm_entity, norm_object
from .ingestion.lexicon import slot_for
from .models import Scope, ScopeLevel
from .providers.base import ProviderError
from .providers.embeddings import BaseEmbeddingProvider, EmbeddingModelMismatch
from .storage.db import Database
from .storage.visibility import write_scope_id
from .util import Clock, IdFactory, parse_ts, sha256, to_ts, ts


def normalize_content(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def content_hash(normalized: str) -> str:
    return sha256(normalized.lower())


def adjust_reliability(base: float, verification: str) -> float:
    if verification == "verified":
        return min(1.0, base + 0.1)
    if verification == "disputed":
        return max(0.05, base - 0.3)
    return base


class Store:
    def __init__(
        self, db: Database, embedder: BaseEmbeddingProvider, settings: Settings, clock: Clock, id_factory: IdFactory
    ):
        self.db = db
        self.embedder = embedder
        self.settings = settings
        self.clock = clock
        self.new_id = id_factory
        self._last_now: datetime | None = None
        self._now_lock = threading.Lock()
        self._embed_lock = threading.RLock()
        self._registered: tuple[str, int, str] | None = None
        self._version_synced: tuple[str, str] | None = None

    def now(self) -> str:
        """Strictly increasing system time.

        Coarse clocks (Windows ~15 ms) return identical values for back-to-back writes. System time orders
        facts and defines "known as of", so it must never repeat: ties are broken by a 1 microsecond bump.
        """
        with self._now_lock:
            current = self.clock()
            if self._last_now is not None and current <= self._last_now:
                current = self._last_now + timedelta(microseconds=1)
            self._last_now = current
            return ts(current)

    # ---- events (tamper-evident append-only log) -----------------------------------------
    def append_event(
        self, conn: sqlite3.Connection, tenant_id: str, actor: str | None, type_: str, memory_id: str | None, payload: dict
    ) -> int:
        prev = conn.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = prev[0] if prev else "genesis"
        when = self.now()
        body = json.dumps(payload, sort_keys=True, default=str)
        h = sha256(f"{prev_hash}|{when}|{tenant_id}|{type_}|{memory_id}|{body}")
        cur = conn.execute(
            "INSERT INTO events(ts, tenant_id, actor, type, memory_id, payload, prev_hash, hash) VALUES(?,?,?,?,?,?,?,?)",
            (when, tenant_id, actor, type_, memory_id, body, prev_hash, h),
        )
        return int(cur.lastrowid)

    def audit(self, tenant_id: str, actor: str | None, action: str, target: str | None = None, detail: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO audit_log(ts, tenant_id, actor, action, target, detail) VALUES(?,?,?,?,?,?)",
            (self.now(), tenant_id, actor, action, target, detail),
        )

    # ---- embeddings ------------------------------------------------------------------------
    @property
    def model_key(self) -> str:
        return self.embedder.name

    def _check_model(self, dim: int) -> bool:
        """Guard + registry for the active embedding model (called whenever vectors are produced).

        * Same model name, different dimension -> ``EmbeddingModelMismatch`` (or reindex when configured).
        * Same model name, different declared version -> its cached vectors are discarded and rebuilt lazily.

        Returns True when cached vectors were discarded (the caller must recompute).
        """
        info = self.embedder.get_model_info()
        state = (info.model, dim, info.version)
        if self._registered == state:
            return False
        dropped = False
        with self._embed_lock:
            row = self.db.one("SELECT * FROM embedding_models WHERE model=?", (info.model,))
            dims = {r[0] for r in self.db.query("SELECT DISTINCT dim FROM embeddings WHERE model=?", (info.model,))}
            if (row and row["dim"] != dim) or (dims - {dim}):
                if self.settings.embedding_on_mismatch != "reindex":
                    raise EmbeddingModelMismatch(
                        f"model '{info.model}' now produces {dim}-dimensional vectors but {sorted(dims | ({row['dim']} if row else set()))} "
                        "are already stored. Use a different model name, or run MemoryOS.reembed(force=True) "
                        "(or set embedding_on_mismatch='reindex')."
                    )
                self.drop_model_vectors(info.model)
                dropped = True
            elif row and row["model_version"] != info.version:
                self.drop_model_vectors(info.model)
                dropped = True
            now = self.now()
            with self.db.tx() as conn:
                conn.execute("UPDATE embedding_models SET active=0 WHERE model != ?", (info.model,))
                conn.execute(
                    "INSERT INTO embedding_models(model, provider, model_version, dim, normalization, first_seen_at, active) VALUES(?,?,?,?,?,?,1)"
                    " ON CONFLICT(model) DO UPDATE SET provider=excluded.provider, model_version=excluded.model_version,"
                    " dim=excluded.dim, normalization=excluded.normalization, active=1",
                    (info.model, info.provider, info.version, dim, info.normalization, now),
                )
            self._registered = state
        return dropped

    def sync_model_version(self) -> bool:
        """Discard cached vectors when the provider reports a new version of the same model name.

        Cheap (no embedding call), so searches can run it before they read any vector.
        """
        info = self.embedder.get_model_info()
        state = (info.model, info.version)
        if self._version_synced == state:
            return False
        dropped = False
        with self._embed_lock:
            row = self.db.one("SELECT model_version FROM embedding_models WHERE model=?", (info.model,))
            if row and row["model_version"] != info.version:
                self.drop_model_vectors(info.model)
                self.db.execute("UPDATE embedding_models SET model_version=? WHERE model=?", (info.version, info.model))
                dropped = True
            self._version_synced = state
        return dropped

    def drop_model_vectors(self, model: str) -> int:
        """Discard cached vectors of one model; they are derived data and are rebuilt from preserved originals."""
        with self.db.tx() as conn:
            n = conn.execute("DELETE FROM embeddings WHERE model=?", (model,)).rowcount
            conn.execute("UPDATE memories SET embedding_model=NULL, embedding_hash=NULL WHERE embedding_model=?", (model,))
        return n

    def embed_texts(self, texts: Sequence[str], *, persist: bool = True) -> np.ndarray:
        """Embed with a content-hash cache so identical text is never embedded twice per model.

        ``persist=False`` (queries, historical snapshots) reads the cache but never writes to it.
        """
        model = self.model_key
        self.sync_model_version()
        hashes = [content_hash(normalize_content(t)) for t in texts]
        found: dict[str, np.ndarray] = {}
        uniq = list(dict.fromkeys(hashes))
        for i in range(0, len(uniq), 500):
            part = uniq[i : i + 500]
            marks = ",".join("?" * len(part))
            for r in self.db.query(
                f"SELECT content_hash, vector, dim FROM embeddings WHERE model=? AND content_hash IN ({marks})",
                [model, *part],
            ):
                found[r["content_hash"]] = np.frombuffer(r["vector"], dtype=np.float32)
        missing = [h for h in uniq if h not in found]
        if missing:
            first_text = {h: t for h, t in zip(hashes, texts, strict=True)}
            vecs = np.asarray(self.embedder.embed([first_text[h] for h in missing]), dtype=np.float32)
            if vecs.ndim != 2 or vecs.shape[0] != len(missing):
                raise ProviderError(f"{model}: expected {len(missing)} vectors, got shape {vecs.shape}")
            if self._check_model(int(vecs.shape[1])):
                return self.embed_texts(texts, persist=persist)
            if not persist:
                for h, v in zip(missing, vecs, strict=True):
                    found[h] = v
                return np.stack([found[h] for h in hashes])
            info = self.embedder.get_model_info()
            now = self.now()
            with self.db.tx() as conn:
                for h, v in zip(missing, vecs, strict=True):
                    found[h] = v
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings(content_hash, model, dim, vector, provider, model_version, normalization, created_at, status)"
                        " VALUES(?,?,?,?,?,?,?,?,'ready')",
                        (h, model, int(v.shape[0]), v.tobytes(), info.provider, info.version, info.normalization, now),
                    )
        return np.stack([found[h] for h in hashes]) if hashes else np.zeros((0, self.embedder.dim), dtype=np.float32)

    # ---- inserts ---------------------------------------------------------------------------
    def insert_source(
        self, conn: sqlite3.Connection, scope: Scope, level: ScopeLevel, *, source_type: str, origin: str | None,
        content: str, reliability: float, verification: str, metadata: dict, file_path: str | None = None
    ) -> str:
        sid = self.new_id("src")
        conn.execute(
            "INSERT INTO sources(id, tenant_id, user_id, scope_level, scope_id, source_type, origin, content, content_hash,"
            " metadata, file_path, reliability, verification, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, scope.tenant_id, scope.user_id, level, write_scope_id(scope, level), source_type, origin, content,
             content_hash(normalize_content(content)), json.dumps(metadata, default=str), file_path, reliability,
             verification, self.now()),
        )
        return sid

    def insert_memory(
        self, conn: sqlite3.Connection, scope: Scope, level: ScopeLevel, *, source_id: str, chunk_index: int,
        original: str, category: str, confidence: float, effective_at: str | None, derived: bool = False,
        metadata: dict | None = None, vector: np.ndarray | None = None,
    ) -> str:
        mid = self.new_id("mem")
        norm = normalize_content(original)
        chash = content_hash(norm)
        now = self.now()
        cur = conn.execute(
            "INSERT INTO memories(id, tenant_id, user_id, scope_level, scope_id, source_id, chunk_index, original_content,"
            " normalized_content, content_hash, category, confidence, created_at, effective_at, updated_at, version, derived,"
            " embedding_hash, embedding_model, metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
            (mid, scope.tenant_id, scope.user_id, level, write_scope_id(scope, level), source_id, chunk_index, original,
             norm, chash, category, confidence, now, effective_at, now, int(derived), chash if vector is not None else None,
             self.embedder.name if vector is not None else None, json.dumps(metadata or {}, default=str)),
        )
        conn.execute("INSERT INTO memories_fts(rowid, content) VALUES(?,?)", (cur.lastrowid, norm))
        conn.execute(
            "INSERT INTO memory_versions(memory_id, version, original_content, normalized_content, changed_at, reason, actor)"
            " VALUES(?,?,?,?,?,?,?)",
            (mid, 1, original, norm, now, "created", scope.user_id),
        )
        return mid

    def insert_facts(
        self, conn: sqlite3.Connection, scope: Scope, level: ScopeLevel, memory_id: str, facts: Sequence[ExtractedFact],
        *, reliability: float, default_valid_from: str | None,
    ) -> int:
        n = 0
        now = self.now()
        for f in facts:
            pv = parse_value(f.object, f.predicate, f.excerpt)
            obj_key = pv.key if pv else norm_object(f.object)
            vf = f.valid_from or default_valid_from
            fid = self.new_id("fact")
            span = f.source_span or (None, None)
            conn.execute(
                "INSERT INTO facts(id, memory_id, tenant_id, user_id, scope_level, scope_id, subject, subject_key, predicate,"
                " object, object_key, slot, valid_from, valid_until, date_precision, recorded_at, extraction_confidence,"
                " source_reliability, excerpt, polarity, extraction_method, extractor_version, source_span_start,"
                " source_span_end, value_num, value_unit, value_currency)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fid, memory_id, scope.tenant_id, scope.user_id, level, write_scope_id(scope, level), f.subject,
                 norm_entity(f.subject), f.predicate, f.object, obj_key, slot_for(f.predicate, f.object), to_ts_or_none(vf),
                 end_exclusive(f.valid_until), f.precision, now, f.confidence, reliability, f.excerpt,
                 f.polarity, f.method, f.extractor_version, span[0], span[1],
                 pv.amount if pv else None, pv.period if pv else None, pv.currency if pv else None),
            )
            self.append_event(conn, scope.tenant_id, scope.user_id, "fact.recorded", memory_id, {"fact_id": fid})
            n += 1
        return n

    def insert_extraction_attempts(self, conn: sqlite3.Connection, tenant_id: str, memory_id: str | None, attempts: Sequence[ExtractionAttempt]) -> None:
        for a in attempts:
            conn.execute(
                "INSERT INTO extraction_attempts(id, memory_id, tenant_id, ts, method, extractor_version, status, error,"
                " n_proposed, n_accepted, n_rejected, latency_ms, detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.new_id("xatt"), memory_id, tenant_id, self.now(), a.method, a.extractor_version, a.status, a.error,
                 a.n_proposed, a.n_accepted, a.n_rejected, a.latency_ms, json.dumps(a.detail, default=str)),
            )

    def insert_mentions(self, conn: sqlite3.Connection, scope: Scope, level: ScopeLevel, memory_id: str, entities: dict[str, str]) -> None:
        for key, name in entities.items():
            conn.execute(
                "INSERT OR IGNORE INTO mentions(memory_id, tenant_id, user_id, scope_level, scope_id, entity_key, entity_name)"
                " VALUES(?,?,?,?,?,?,?)",
                (memory_id, scope.tenant_id, scope.user_id, level, write_scope_id(scope, level), key, name),
            )

    def retract_facts(self, conn: sqlite3.Connection, memory_id: str) -> int:
        cur = conn.execute("UPDATE facts SET retracted_at=? WHERE memory_id=? AND retracted_at IS NULL", (self.now(), memory_id))
        return cur.rowcount

    def delete_memory_rows(self, conn: sqlite3.Connection, memory_id: str) -> None:
        """Hard-delete a memory and everything derived from it (search, facts, graph, versions, vectors)."""
        row = conn.execute("SELECT rowid, source_id, embedding_hash, embedding_model FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not row:
            return
        source_ids = {row["source_id"]} | {r[0] for r in conn.execute("SELECT source_id FROM memory_provenance WHERE memory_id=?", (memory_id,))}
        conn.execute("DELETE FROM memories_fts WHERE rowid=?", (row["rowid"],))
        for table in ("facts", "mentions", "memory_versions", "memory_provenance", "extraction_attempts"):
            conn.execute(f"DELETE FROM {table} WHERE memory_id=?", (memory_id,))
        conn.execute("DELETE FROM memory_links WHERE src_id=? OR dst_id=?", (memory_id, memory_id))
        conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        if row["embedding_hash"]:
            still = conn.execute("SELECT 1 FROM memories WHERE embedding_hash=? LIMIT 1", (row["embedding_hash"],)).fetchone()
            if not still:
                conn.execute("DELETE FROM embeddings WHERE content_hash=?", (row["embedding_hash"],))
        for sid in source_ids:
            used = conn.execute("SELECT 1 FROM memories WHERE source_id=? LIMIT 1", (sid,)).fetchone()
            prov = conn.execute("SELECT 1 FROM memory_provenance WHERE source_id=? LIMIT 1", (sid,)).fetchone()
            if not used and not prov:
                src = conn.execute("SELECT file_path FROM sources WHERE id=?", (sid,)).fetchone()
                conn.execute("DELETE FROM sources WHERE id=?", (sid,))
                if src and src["file_path"]:
                    from pathlib import Path

                    Path(src["file_path"]).unlink(missing_ok=True)


def to_ts_or_none(v: str | None) -> str | None:
    return to_ts(v) if v else None


def end_exclusive(v: str | None) -> str | None:
    """A date-only 'until' value means through the end of that day, i.e. exclusive next midnight."""
    if not v:
        return None
    if len(v) == 10:
        from datetime import timedelta

        return ts(parse_ts(v) + timedelta(days=1))
    return to_ts(v)
