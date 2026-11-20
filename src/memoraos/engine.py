"""MemoryOS: the public engine tying storage, extraction, routing, truth and consolidation together."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import Settings
from .extraction.base import MemoryExtractor
from .extraction.pipeline import build_extractor
from .extraction.schema import ExtractionResult
from .ingestion.classify import chunk_text, classify_category
from .ingestion.dates import extract_dates
from .ingestion.extract import ExtractedFact
from .models import (
    SOURCE_RELIABILITY,
    Contradiction,
    Fact,
    MemoryRecord,
    RememberResult,
    Scope,
    ScopeLevel,
)
from .models import RecallResult as RecallResultModel
from .providers.base import (
    ChatProvider,
    EmbeddingProvider,
    EntityExtractor,
    ProviderError,
    RerankProvider,
    Usage,
)
from .providers.embeddings import BaseEmbeddingProvider, adapt_embedder
from .providers.local import HashingEmbedder, LexicalReranker
from .recall import LatentBackend, Recaller
from .retrieval.facts import load_facts
from .retrieval.vector import VectorIndex
from .routing.learning import make_policy, strategy_stats
from .routing.router import AdaptiveRouter
from .security import detect_prompt_injection, redact_secrets
from .storage.crypto import ENV_KEY
from .storage.db import Database
from .storage.visibility import visibility_clause, write_scope_id
from .store import Store, adjust_reliability, content_hash, normalize_content
from .truth.timeline import build_timeline
from .util import Clock, IdFactory, new_id, to_ts, utcnow

MAX_TEXT_CHARS = 2_000_000


class NotFoundError(KeyError):
    """The memory does not exist or is not visible to the requester."""


class PermissionDenied(PermissionError):
    """The requester may see this memory but may not modify it."""


class MemoryOS:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        embedder: EmbeddingProvider | None = None,
        chat: ChatProvider | None = None,
        reranker: RerankProvider | None = None,
        entity_extractor: EntityExtractor | None = None,
        router_classifier: ChatProvider | None = None,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        latent: LatentBackend | None = None,
        extractor: MemoryExtractor | None = None,
    ):
        self.settings = settings or Settings()
        self.clock: Clock = clock or utcnow
        self.new_id: IdFactory = id_factory or new_id
        self.db = Database(
            self.settings.db_path if str(self.settings.db_path) != ":memory:" else ":memory:",
            self.settings.encryption_passphrase or os.environ.get(ENV_KEY) or None,
        )
        self.embedder: BaseEmbeddingProvider = adapt_embedder(embedder or HashingEmbedder(self.settings.embedding_dim))
        self.chat = chat
        self.reranker: RerankProvider = reranker or LexicalReranker()
        self.entity_extractor = entity_extractor
        self._extract_cache: dict[tuple[str, str], ExtractionResult] = {}
        self.extractor: MemoryExtractor = extractor or build_extractor(
            self.settings.extraction_mode, chat, usage_sink=self.record_usage, strict=self.settings.extraction_strict
        )
        self.store = Store(self.db, self.embedder, self.settings, self.clock, self.new_id)
        self.vectors = VectorIndex(self.db, self.store)
        self.router = AdaptiveRouter(self.settings, classifier=router_classifier)
        self.recaller = Recaller(self.db, self.store, self.settings, self.router, self.vectors, self.clock, chat=chat, latent=latent, reranker=self.reranker)
        self._scheduler = None
        self.recaller.usage_sink = self.record_usage

    # ------------------------------------------------------------------ construction
    @classmethod
    def local(cls, path: str | Path | None = None, **kwargs: Any) -> MemoryOS:
        """Create an on-disk instance (default ``./.memoraos``) with zero configuration and no network."""
        settings = kwargs.pop("settings", None) or Settings()
        if path is not None:
            if str(path) == ":memory:":
                settings = settings.model_copy(update={"data_dir": Path("."), "db_filename": ":memory:"})
            else:
                settings = settings.model_copy(update={"data_dir": Path(path)})
        return cls(settings, **kwargs)

    @classmethod
    def in_memory(cls, **kwargs: Any) -> MemoryOS:
        return cls.local(":memory:", **kwargs)

    def close(self) -> None:
        if self._scheduler:
            self._scheduler.stop()
        self.db.close()

    def __enter__(self) -> MemoryOS:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def record_usage(self, usage: Usage) -> None:
        """Usage sink for providers; feeds token and cost analytics."""
        self.db.execute(
            "INSERT INTO provider_usage(ts, provider, model, kind, tokens_in, tokens_out, cost, latency_ms) VALUES(?,?,?,?,?,?,?,?)",
            (self.store.now(), usage.provider, usage.model, usage.kind, usage.tokens_in, usage.tokens_out, usage.cost, usage.latency_ms),
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def scope_for(user_id: str, tenant_id: str = "default", agent_id: str | None = None, session_id: str | None = None, project_id: str | None = None) -> Scope:
        return Scope(tenant_id=tenant_id, user_id=user_id, agent_id=agent_id, session_id=session_id, project_id=project_id)

    def _owned(self, scope: Scope, memory_id: str, *, write: bool = False) -> Any:
        vis, params = visibility_clause(scope, "m")
        row = self.db.one(f"SELECT m.* FROM memories m WHERE m.id=? AND m.status IN ('active','inactive') AND {vis}", [memory_id, *params])
        if not row:
            raise NotFoundError(memory_id)
        if write and row["user_id"] != scope.user_id:
            raise PermissionDenied("only the memory's creator may modify or delete it")
        return row

    # ------------------------------------------------------------------ remember
    def remember(
        self,
        text: str,
        *,
        user_id: str,
        tenant_id: str = "default",
        agent_id: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        level: ScopeLevel = "user",
        source_type: str = "user_statement",
        origin: str | None = None,
        category: str | None = None,
        effective_at: str | None = None,
        reliability: float | None = None,
        verification: str = "unverified",
        metadata: dict | None = None,
        facts: Sequence[dict | ExtractedFact] | None = None,
        extract: bool = True,
        file_path: str | None = None,
    ) -> RememberResult:
        """Store text. Original content is always preserved; facts and entities are extracted for reasoning."""
        if not text or not text.strip():
            raise ValueError("text must be non-empty")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"text exceeds {MAX_TEXT_CHARS} characters")
        if source_type not in SOURCE_RELIABILITY:
            raise ValueError(f"unknown source_type '{source_type}'")
        if reliability is not None and not 0.0 <= reliability <= 1.0:
            raise ValueError("reliability must be within [0, 1]")
        scope = self.scope_for(user_id, tenant_id, agent_id, session_id, project_id)
        write_scope_id(scope, level)  # validates the level has the id it needs
        redactions = 0
        if self.settings.redact_secrets:
            text, redactions = redact_secrets(text)
        eff = to_ts(effective_at) if effective_at else None
        base_rel = SOURCE_RELIABILITY[source_type] if reliability is None else reliability
        rel = adjust_reliability(base_rel, verification)
        chunks = chunk_text(text, self.settings.chunk_chars, self.settings.chunk_overlap) or [text.strip()]
        vectors = self.store.embed_texts(chunks)
        explicit = [_to_extracted(f) for f in facts] if facts else None
        # extraction runs before the write transaction so a slow model call never holds the database lock
        extractions = self._extract_chunks(scope, level, chunks, explicit, extract)

        memory_ids: list[str] = []
        dup_of: str | None = None
        facts_recorded = 0
        touched: list[Fact] = []
        with self.db.tx() as conn:
            sid = self.store.insert_source(
                conn, scope, level, source_type=source_type, origin=origin, content=text, reliability=rel,
                verification=verification, metadata=metadata or {}, file_path=file_path,
            )
            for i, chunk in enumerate(chunks):
                norm = normalize_content(chunk)
                chash = content_hash(norm)
                extraction = extractions[i] or ExtractionResult()
                chunk_facts = extraction.facts
                mem_eff = eff or _text_date(chunk)
                existing = conn.execute(
                    "SELECT id FROM memories WHERE tenant_id=? AND scope_level=? AND scope_id=? AND content_hash=? AND status='active' AND derived=0",
                    (scope.tenant_id, level, write_scope_id(scope, level), chash),
                ).fetchone()
                if existing:
                    mid = existing["id"]
                    dup_of = dup_of or mid
                    conn.execute("UPDATE memories SET mention_count = mention_count + 1, updated_at=? WHERE id=?", (self.store.now(), mid))
                    conn.execute("INSERT OR IGNORE INTO memory_provenance(memory_id, source_id, seen_at) VALUES(?,?,?)", (mid, sid, self.store.now()))
                    self.store.append_event(conn, scope.tenant_id, user_id, "memory.duplicate_seen", mid, {"source_id": sid})
                else:
                    cat = category or classify_category(chunk, source_type)
                    md = dict(metadata or {})
                    if detect_prompt_injection(chunk):
                        md["flags"] = ["possible_prompt_injection"]
                    mid = self.store.insert_memory(
                        conn, scope, level, source_id=sid, chunk_index=i, original=chunk, category=cat,
                        confidence=1.0, effective_at=mem_eff, metadata=md, vector=vectors[i],
                    )
                    entities = self.extractor.extract_entities(chunk, chunk_facts)
                    if self.entity_extractor:
                        try:
                            entities.update({e.lower(): e for e in self.entity_extractor.extract(chunk).entities})
                        except Exception:  # noqa: BLE001 - optional enrichment must not block ingestion
                            pass
                    self.store.insert_mentions(conn, scope, level, mid, entities)
                    self.store.insert_extraction_attempts(conn, scope.tenant_id, mid, extraction.attempts)
                    self.store.append_event(conn, scope.tenant_id, user_id, "memory.created", mid, {"source_id": sid, "category": cat, "version": 1})
                memory_ids.append(mid)
                if chunk_facts:
                    facts_recorded += self.store.insert_facts(conn, scope, level, mid, chunk_facts, reliability=rel, default_valid_from=mem_eff)
        if facts_recorded:
            touched = self._facts_for_slots(scope, memory_ids)
        conflicts = self._open_conflicts(touched)
        return RememberResult(memory_ids=memory_ids, source_id=sid, duplicate_of=dup_of, facts_recorded=facts_recorded, conflicts=conflicts, redactions=redactions)

    def _extract_chunks(
        self, scope: Scope, level: ScopeLevel, chunks: list[str], explicit: list[ExtractedFact] | None, extract: bool
    ) -> list[ExtractionResult | None]:
        out: list[ExtractionResult | None] = []
        for i, chunk in enumerate(chunks):
            if explicit is not None:
                out.append(ExtractionResult(facts=explicit if i == 0 else []))
            elif not extract:
                out.append(ExtractionResult())
            else:
                out.append(self._extract_cached(chunk))
        return out

    def _extract_cached(self, chunk: str) -> ExtractionResult:
        """Exact repeats (restatements) re-use the earlier extraction so a model is not paid twice for the same text."""
        key = (self.extractor.version, chunk)
        hit = self._extract_cache.get(key)
        if hit is not None:
            return ExtractionResult(facts=list(hit.facts), attempts=[])
        res = self.extractor.extract(chunk)
        if len(self._extract_cache) >= 256:
            self._extract_cache.pop(next(iter(self._extract_cache)))
        self._extract_cache[key] = res
        return res

    def remember_conversation(
        self, messages: Sequence[dict], *, user_id: str, tenant_id: str = "default", session_id: str | None = None,
        agent_id: str | None = None, project_id: str | None = None,
    ) -> list[RememberResult]:
        """Store a chat transcript. Each message becomes an episodic memory; assistant turns are lower reliability."""
        out = []
        for m in messages:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            role = m.get("role", "user")
            out.append(
                self.remember(
                    content, user_id=user_id, tenant_id=tenant_id, session_id=session_id, agent_id=agent_id, project_id=project_id,
                    level="session" if session_id else "user", source_type="conversation" if role == "user" else "inferred",
                    effective_at=m.get("timestamp"), category="episodic", metadata={"role": role, "session_id": session_id},
                    extract=role == "user",
                )
            )
        return out

    def remember_json(self, record: dict | list, *, user_id: str, subject: str | None = None, **kwargs: Any) -> list[RememberResult]:
        """Store structured data. Records shaped like {subject, predicate, object|value, valid_from?, valid_until?}
        become explicit facts; other dicts are flattened to ``key: value`` text about ``subject``."""
        records = record if isinstance(record, list) else [record]
        results = []
        for rec in records:
            if not isinstance(rec, dict):
                raise ValueError("structured records must be JSON objects")
            if {"subject", "predicate"} <= rec.keys() and ("object" in rec or "value" in rec):
                obj = str(rec.get("object", rec.get("value")))
                text = f"{rec['subject']} {str(rec['predicate']).replace('_', ' ')}: {obj}"
                fact = {"subject": rec["subject"], "predicate": rec["predicate"], "object": obj, "valid_from": rec.get("valid_from"), "valid_until": rec.get("valid_until")}
                results.append(self.remember(text, user_id=user_id, source_type="structured", facts=[fact], effective_at=rec.get("valid_from"), **kwargs))
            else:
                subj = subject or str(rec.get("name") or rec.get("id") or "record")
                lines = [f"{subj} {k.replace('_', ' ')}: {v}" for k, v in _flatten(rec) if v not in (None, "")]
                facts_ = [{"subject": subj, "predicate": k.replace("_", " "), "object": str(v)} for k, v in _flatten(rec) if v not in (None, "") and k not in ("name", "id")]
                results.append(self.remember("\n".join(lines) or json.dumps(rec), user_id=user_id, source_type="structured", facts=facts_, **kwargs))
        return results

    def ingest_document(self, path: str | Path, *, user_id: str, **kwargs: Any) -> RememberResult:
        """Copy a text document into the data directory and ingest it with chunking."""
        src = Path(path)
        if not src.is_file():
            raise FileNotFoundError(str(src))
        text = src.read_text(encoding="utf-8", errors="replace")
        if self.db.path == ":memory:":
            import tempfile

            dest_dir = Path(tempfile.gettempdir()) / "memoraos-sources"
        else:
            dest_dir = Path(self.settings.data_dir) / "sources"
        kwargs.setdefault("source_type", "document")
        if self.db.encrypted:  # a plaintext copy would defeat encryption at rest; the content is stored in the database
            return self.remember(text, user_id=user_id, origin=str(src), **kwargs)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{content_hash(normalize_content(text))[:16]}_{src.name}"
        shutil.copyfile(src, dest)
        return self.remember(text, user_id=user_id, origin=str(src), file_path=str(dest), **kwargs)

    def _facts_for_slots(self, scope: Scope, memory_ids: list[str]) -> list[Fact]:
        return load_facts(self.db, scope, memory_ids=list(set(memory_ids)))

    def _open_conflicts(self, new_facts: list[Fact]) -> list[Contradiction]:
        out: list[Contradiction] = []
        seen: set[tuple] = set()
        for f in new_facts:
            if not f.slot or (f.subject_key, f.slot) in seen:
                continue
            seen.add((f.subject_key, f.slot))
            scope = self._scope_of_fact(f)
            if scope is None:
                continue
            same = [x for x in load_facts(self.db, scope, subject_keys=[f.subject_key]) if x.slot == f.slot]
            if len({x.object_key for x in same}) > 1:
                out.extend(c for c in build_timeline(same).contradictions if not c.resolved)
        return out

    def _scope_of_fact(self, f: Fact) -> Scope | None:
        row = self.db.one("SELECT tenant_id, user_id, scope_level, scope_id FROM facts WHERE id=?", (f.id,))
        if not row:
            return None
        kw: dict[str, str | None] = {"agent_id": None, "session_id": None, "project_id": None}
        if row["scope_level"] in ("agent", "session", "project"):
            kw[f"{row['scope_level']}_id"] = row["scope_id"]
        return Scope(tenant_id=row["tenant_id"], user_id=row["user_id"], **kw)

    # ------------------------------------------------------------------ recall & friends
    def recall(
        self, query: str, *, user_id: str, tenant_id: str = "default", agent_id: str | None = None, session_id: str | None = None,
        project_id: str | None = None, top_k: int | None = None, as_of: str | None = None, strategy: str | None = None,
        synthesize: bool = False, use_cache: bool = True,
    ) -> RecallResultModel:
        """Answer a question from memory, returning the answer, evidence, and the strategy that produced it."""
        scope = self.scope_for(user_id, tenant_id, agent_id, session_id, project_id)
        if self.settings.adaptive_learning:
            self.router.learned_policy = make_policy(self.db, tenant_id, self.settings.learning_min_samples)
        return self.recaller.recall(scope, query, top_k=top_k, as_of=to_ts(as_of) if as_of else None, strategy=strategy, synthesize=synthesize, use_cache=use_cache)

    def what_did_you_know(self, query: str, as_of: str, **kwargs: Any) -> RecallResultModel:
        """Time travel: answer using only what had been recorded by ``as_of``."""
        return self.recall(query, as_of=as_of, **kwargs)

    def feedback(self, recall_id: str, *, correct: bool | None = None, relevance: float | None = None, comment: str | None = None) -> None:
        if not self.db.one("SELECT 1 FROM retrieval_log WHERE id=?", (recall_id,)):
            raise NotFoundError(recall_id)
        self.db.execute(
            "INSERT INTO feedback(recall_id, ts, correct, relevance, comment) VALUES(?,?,?,?,?)",
            (recall_id, self.store.now(), None if correct is None else int(correct), relevance, comment),
        )

    def strategy_report(self, tenant_id: str = "default") -> list[dict]:
        return [{"category": s.category, "strategy": s.strategy, "n": s.n, "accuracy": round(s.accuracy, 4), "mean_latency_ms": round(s.mean_latency_ms, 3), "mean_context_tokens": round(s.mean_tokens, 1)} for s in strategy_stats(self.db, tenant_id)]

    def explain(self, recall_id: str, *, user_id: str, tenant_id: str = "default") -> dict:
        row = self.db.one("SELECT * FROM retrieval_log WHERE id=? AND tenant_id=? AND user_id=?", (recall_id, tenant_id, user_id))
        if not row:
            raise NotFoundError(recall_id)
        explanation = json.loads(row["explanation"])
        return {
            "recall_id": recall_id, "query": row["query"], "category": row["category"], "strategy": row["strategy"],
            "strategies_tried": json.loads(row["strategies_tried"]), "status": row["status"], "answer": row["answer"],
            "plan": json.loads(row["plan"]), "evidence_memory_ids": json.loads(row["evidence_ids"]), "as_of": row["as_of"], **explanation,
        }

    # ------------------------------------------------------------------ read / list
    def get(self, memory_id: str, *, user_id: str, tenant_id: str = "default", agent_id: str | None = None, session_id: str | None = None, project_id: str | None = None) -> MemoryRecord:
        scope = self.scope_for(user_id, tenant_id, agent_id, session_id, project_id)
        row = self._owned(scope, memory_id)
        return self._record(row)

    def _record(self, row: Any) -> MemoryRecord:
        src = self.db.one("SELECT source_type, reliability, verification FROM sources WHERE id=?", (row["source_id"],))
        return MemoryRecord(
            id=row["id"], source_id=row["source_id"], original_content=row["original_content"], normalized_content=row["normalized_content"],
            category=row["category"], scope_level=row["scope_level"], user_id=row["user_id"], created_at=row["created_at"],
            effective_at=row["effective_at"], updated_at=row["updated_at"], version=row["version"], confidence=row["confidence"],
            source_type=src["source_type"], source_reliability=src["reliability"], verification=src["verification"],
            derived=bool(row["derived"]), mention_count=row["mention_count"], importance=row["importance"], duplicate_of=row["duplicate_of"],
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def list_memories(
        self, *, user_id: str, tenant_id: str = "default", agent_id: str | None = None, session_id: str | None = None,
        project_id: str | None = None, category: str | None = None, limit: int = 100, offset: int = 0, include_derived: bool = True,
    ) -> list[MemoryRecord]:
        scope = self.scope_for(user_id, tenant_id, agent_id, session_id, project_id)
        vis, params = visibility_clause(scope, "m")
        where, args = ["m.status='active'", vis], list(params)
        if category:
            where.append("m.category=?")
            args.append(category)
        if not include_derived:
            where.append("m.derived=0")
        rows = self.db.query(f"SELECT m.* FROM memories m WHERE {' AND '.join(where)} ORDER BY m.rowid DESC LIMIT ? OFFSET ?", [*args, limit, offset])
        return [self._record(r) for r in rows]

    def facts(self, *, user_id: str, tenant_id: str = "default", as_of: str | None = None, **scope_kw: Any) -> list[Fact]:
        """All stored facts including negated ones (see ``Fact.polarity``)."""
        return load_facts(self.db, self.scope_for(user_id, tenant_id, **scope_kw), as_of=to_ts(as_of) if as_of else None, include_negated=True)

    def rebuild_facts(self, *, user_id: str, tenant_id: str = "default", dry_run: bool = False, **scope_kw: Any) -> dict:
        """Re-derive facts from the PRESERVED original text with the current extractor.

        Old facts are retracted (kept for time travel), never deleted. Facts supplied explicitly by the caller
        (structured records) cannot be re-derived from text and are left untouched. Use after upgrading from v0.1
        or after switching ``extraction_mode``; ``dry_run`` reports what would change without writing.
        """
        scope = self.scope_for(user_id, tenant_id, **scope_kw)
        vis, params = visibility_clause(scope, "m")
        rows = self.db.query(
            f"SELECT m.id, m.scope_level, m.original_content, m.effective_at, m.source_id FROM memories m WHERE m.status='active' AND m.derived=0 AND m.user_id=? AND {vis} ORDER BY m.rowid",
            [user_id, *params],
        )
        report = {"memories": 0, "skipped_explicit": 0, "facts_retracted": 0, "facts_inserted": 0, "dry_run": dry_run}
        for row in rows:
            if self.db.one("SELECT 1 FROM facts WHERE memory_id=? AND extraction_method='explicit' AND retracted_at IS NULL LIMIT 1", (row["id"],)):
                report["skipped_explicit"] += 1
                continue
            extraction = self.extractor.extract(row["original_content"])
            report["memories"] += 1
            old = self.db.one("SELECT COUNT(*) FROM facts WHERE memory_id=? AND retracted_at IS NULL", (row["id"],))[0]
            report["facts_retracted"] += old
            report["facts_inserted"] += len(extraction.facts)
            if dry_run:
                continue
            reliability = self.db.one("SELECT reliability FROM sources WHERE id=?", (row["source_id"],))["reliability"]
            with self.db.tx() as conn:
                self.store.retract_facts(conn, row["id"])
                self.store.insert_facts(conn, scope, row["scope_level"], row["id"], extraction.facts, reliability=reliability, default_valid_from=row["effective_at"])
                self.store.insert_extraction_attempts(conn, tenant_id, row["id"], extraction.attempts)
                self.store.append_event(conn, tenant_id, user_id, "memory.facts_rebuilt", row["id"], {"retracted": old, "inserted": len(extraction.facts), "extractor": self.extractor.version})
        return report

    def contradictions(self, *, user_id: str, tenant_id: str = "default", include_resolved: bool = True, **scope_kw: Any) -> list[Contradiction]:
        """Every conflict or version change across the visible facts."""
        facts = [f for f in load_facts(self.db, self.scope_for(user_id, tenant_id, **scope_kw)) if f.slot]
        groups: dict[tuple, list[Fact]] = {}
        for f in facts:
            groups.setdefault((f.subject_key, f.slot), []).append(f)
        out = []
        for fs in groups.values():
            if len({f.object_key for f in fs}) > 1:
                out.extend(c for c in build_timeline(fs).contradictions if include_resolved or not c.resolved)
        return out

    # ------------------------------------------------------------------ embedding maintenance
    def reembed(self, *, tenant_id: str = "default", force: bool = False, batch_size: int = 64, prune_stale: bool = False) -> dict:
        """Embed every memory with the CURRENT model (e.g. after switching providers).

        Re-embedding is derived from the preserved original text, so nothing is lost. Batches that fail (provider
        outage) are counted and skipped, leaving those memories on their previous vectors; call again to finish.
        Vectors of other models are kept (marked stale) so a rollback is possible, unless ``prune_stale``.
        """
        model = self.store.model_key
        if force:
            self.store.drop_model_vectors(model)
            self.store._registered = None
        rows = self.db.query(
            "SELECT m.id, m.normalized_content FROM memories m WHERE m.tenant_id=? AND m.status='active'"
            " AND (m.embedding_model IS NULL OR m.embedding_model != ?) ORDER BY m.rowid",
            (tenant_id, model),
        )
        embedded = failed = 0
        errors: list[str] = []
        for i in range(0, len(rows), max(1, batch_size)):
            part = rows[i : i + batch_size]
            try:
                self.store.embed_texts([r["normalized_content"] for r in part])
            except ProviderError as exc:
                failed += len(part)
                errors.append(str(exc)[:200])
                continue
            with self.db.tx() as conn:
                for r in part:
                    conn.execute("UPDATE memories SET embedding_hash=?, embedding_model=? WHERE id=?", (content_hash(r["normalized_content"]), model, r["id"]))
            embedded += len(part)
        with self.db.tx() as conn:
            if failed == 0:
                conn.execute("UPDATE embeddings SET status='stale' WHERE model != ?", (model,))
            if prune_stale and failed == 0:
                conn.execute("DELETE FROM embeddings WHERE status='stale'")
        self.vectors.invalidate()
        return {"model": model, "embedded": embedded, "failed": failed, "remaining": failed, "errors": errors[:5], "forced": force}

    def rebuild_index(self, *, tenant_id: str = "default") -> dict:
        """Rebuild every search index from the stored originals: vectors for the current model and the full-text index."""
        report = self.reembed(tenant_id=tenant_id)
        with self.db.tx() as conn:
            conn.execute("DELETE FROM memories_fts")
            rows = conn.execute("SELECT rowid, normalized_content FROM memories WHERE status='active'").fetchall()
            conn.executemany("INSERT INTO memories_fts(rowid, content) VALUES(?,?)", [(r["rowid"], r["normalized_content"]) for r in rows])
        self.vectors.invalidate()
        return {**report, "fts_rows": len(rows)}

    def embedding_info(self, *, deep: bool = False) -> dict:
        info = self.embedder.get_model_info().to_dict()
        stored = self.db.query("SELECT model, provider, model_version, dim, active FROM embedding_models ORDER BY first_seen_at")
        out = {"active": info, "registered": [dict(r) for r in stored]}
        if deep:
            h = self.embedder.health_check()
            out["health"] = {"ok": h.ok, "detail": h.detail, "latency_ms": round(h.latency_ms, 2)}
        return out

    # ------------------------------------------------------------------ correct / verify / forget
    def correct(self, memory_id: str, new_content: str, *, user_id: str, tenant_id: str = "default", reason: str | None = None, **scope_kw: Any) -> MemoryRecord:
        """Create a new version of a memory. Old facts are retracted (not erased) so history stays reconstructable."""
        if not new_content.strip():
            raise ValueError("new_content must be non-empty")
        scope = self.scope_for(user_id, tenant_id, **scope_kw)
        row = self._owned(scope, memory_id, write=True)
        if self.settings.redact_secrets:
            new_content, _ = redact_secrets(new_content)
        norm = normalize_content(new_content)
        self.store.embed_texts([new_content])  # warms the embedding cache used by vector search
        level = row["scope_level"]
        src = self.db.one("SELECT reliability FROM sources WHERE id=?", (row["source_id"],))
        extraction = self.extractor.extract(new_content)
        new_facts = extraction.facts
        with self.db.tx() as conn:
            version = row["version"] + 1
            now = self.store.now()
            conn.execute("DELETE FROM memories_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)", (memory_id,))
            conn.execute(
                "UPDATE memories SET original_content=?, normalized_content=?, content_hash=?, version=?, updated_at=?, embedding_hash=?, embedding_model=? WHERE id=?",
                (new_content, norm, content_hash(norm), version, now, content_hash(norm), self.embedder.name, memory_id),
            )
            conn.execute("INSERT INTO memories_fts(rowid, content) VALUES((SELECT rowid FROM memories WHERE id=?), ?)", (memory_id, norm))
            conn.execute(
                "INSERT INTO memory_versions(memory_id, version, original_content, normalized_content, changed_at, reason, actor) VALUES(?,?,?,?,?,?,?)",
                (memory_id, version, new_content, norm, now, reason or "correction", user_id),
            )
            retracted = self.store.retract_facts(conn, memory_id)
            conn.execute("DELETE FROM mentions WHERE memory_id=?", (memory_id,))
            entities = self.extractor.extract_entities(new_content, new_facts)
            self.store.insert_mentions(conn, scope, level, memory_id, entities)
            self.store.insert_extraction_attempts(conn, tenant_id, memory_id, extraction.attempts)
            if new_facts:
                self.store.insert_facts(conn, scope, level, memory_id, new_facts, reliability=src["reliability"], default_valid_from=row["effective_at"])
            self.store.append_event(conn, tenant_id, user_id, "memory.corrected", memory_id, {"from_version": row["version"], "to_version": version, "reason": reason, "facts_retracted": retracted})
            # derived summaries built from the old text are no longer trustworthy
            for r in conn.execute("SELECT src_id FROM memory_links WHERE dst_id=? AND type='derived_from'", (memory_id,)).fetchall():
                conn.execute("UPDATE memories SET status='inactive' WHERE id=? AND derived=1", (r["src_id"],))
        self.vectors.invalidate()
        return self.get(memory_id, user_id=user_id, tenant_id=tenant_id, **scope_kw)

    def verify(self, memory_id: str, status: str, *, user_id: str, tenant_id: str = "default", **scope_kw: Any) -> None:
        if status not in ("unverified", "verified", "disputed"):
            raise ValueError("status must be unverified, verified or disputed")
        scope = self.scope_for(user_id, tenant_id, **scope_kw)
        row = self._owned(scope, memory_id, write=True)
        src = self.db.one("SELECT source_type, verification FROM sources WHERE id=?", (row["source_id"],))
        base = SOURCE_RELIABILITY[src["source_type"]]
        with self.db.tx() as conn:
            conn.execute("UPDATE sources SET verification=?, reliability=? WHERE id=?", (status, adjust_reliability(base, status), row["source_id"]))
            conn.execute("UPDATE facts SET source_reliability=? WHERE memory_id=?", (adjust_reliability(base, status), memory_id))
            self.store.append_event(conn, tenant_id, user_id, "memory.verification", memory_id, {"status": status})

    def forget(self, memory_id: str | None = None, *, user_id: str, tenant_id: str = "default", everything: bool = False, **scope_kw: Any) -> int:
        """Hard-delete memories (and search entries, facts, graph edges, vectors, derived summaries, logs).

        Only an append-only event stub (id, no content) remains in the audit chain. Database backups taken earlier
        are not rewritten; see docs/SECURITY.md.
        """
        scope = self.scope_for(user_id, tenant_id, **scope_kw)
        if everything:
            ids = [r["id"] for r in self.db.query("SELECT id FROM memories WHERE tenant_id=? AND user_id=? AND scope_level IN ('user','session')", (tenant_id, user_id))]
        else:
            if not memory_id:
                raise ValueError("memory_id is required unless everything=True")
            self._owned(scope, memory_id, write=True)
            ids = [memory_id]
        deleted = 0
        with self.db.tx() as conn:
            for mid in ids:
                derived = [r["src_id"] for r in conn.execute("SELECT src_id FROM memory_links WHERE dst_id=? AND type='derived_from'", (mid,))]
                for d in derived:
                    self.store.delete_memory_rows(conn, d)
                self.store.delete_memory_rows(conn, mid)
                conn.execute("DELETE FROM feedback WHERE recall_id IN (SELECT id FROM retrieval_log WHERE evidence_ids LIKE ?)", (f'%"{mid}"%',))
                conn.execute("DELETE FROM retrieval_log WHERE evidence_ids LIKE ?", (f'%"{mid}"%',))
                self.store.append_event(conn, tenant_id, user_id, "memory.forgotten", mid, {"cascaded_derived": len(derived)})
                deleted += 1
            if everything:
                conn.execute("DELETE FROM retrieval_log WHERE tenant_id=? AND user_id=?", (tenant_id, user_id))
                conn.execute("DELETE FROM aliases WHERE tenant_id=? AND user_id=?", (tenant_id, user_id))
        self.vectors.invalidate()
        self.recaller._cache.clear()
        self.recaller._graph_cache = None
        return deleted

    # ------------------------------------------------------------------ history / time travel
    def history(self, memory_id: str | None = None, *, user_id: str, tenant_id: str = "default", subject: str | None = None, predicate: str | None = None, **scope_kw: Any) -> dict:
        """Version history of a memory, or the full value timeline of a (subject, predicate)."""
        scope = self.scope_for(user_id, tenant_id, **scope_kw)
        if memory_id:
            self._owned(scope, memory_id)
            versions = self.db.query("SELECT version, original_content, changed_at, reason, actor FROM memory_versions WHERE memory_id=? ORDER BY version", (memory_id,))
            events = self.db.query("SELECT seq, ts, type, payload FROM events WHERE memory_id=? ORDER BY seq", (memory_id,))
            return {"memory_id": memory_id, "versions": [dict(v) for v in versions], "events": [{**dict(e), "payload": json.loads(e["payload"])} for e in events]}
        if subject and predicate:
            from .ingestion.extract import norm_entity, norm_predicate

            fs = [f for f in load_facts(self.db, scope, subject_keys=[norm_entity(subject)], predicates=[norm_predicate(predicate)])]
            if not fs:
                return {"subject": subject, "predicate": predicate, "timeline": [], "contradictions": []}
            tl = build_timeline(fs)
            return {"subject": subject, "predicate": predicate, "timeline": [e.model_dump() for e in tl.entries(self.store.now())], "contradictions": [c.model_dump() for c in tl.contradictions]}
        raise ValueError("provide memory_id, or subject and predicate")

    def snapshot(self, as_of: str, *, user_id: str, tenant_id: str = "default", **scope_kw: Any) -> dict:
        """Everything the system knew at ``as_of`` (memory text as of then; nothing learned later)."""
        scope = self.scope_for(user_id, tenant_id, **scope_kw)
        at = to_ts(as_of)
        snap = self.recaller._snapshot(scope, at)
        facts = load_facts(self.db, scope, as_of=at)
        return {"as_of": at, "memories": [{"id": k, "content": v} for k, v in snap.items()], "facts": [f.model_dump() for f in facts]}

    def changes(self, since: str, until: str | None = None, *, user_id: str, tenant_id: str = "default") -> list[dict]:
        """Change log (before/after) of this user's memories between two instants."""
        a, b = to_ts(since), to_ts(until) if until else self.store.now()
        rows = self.db.query(
            "SELECT e.seq, e.ts, e.type, e.memory_id, e.payload FROM events e LEFT JOIN memories m ON m.id = e.memory_id"
            " WHERE e.tenant_id=? AND e.ts > ? AND e.ts <= ? AND (m.user_id=? OR (m.id IS NULL AND e.actor=?)) AND e.type != 'fact.recorded' ORDER BY e.seq",
            (tenant_id, a, b, user_id, user_id),
        )
        out = []
        for r in rows:
            item = {"seq": r["seq"], "ts": r["ts"], "type": r["type"], "memory_id": r["memory_id"], "details": json.loads(r["payload"])}
            if r["type"] == "memory.corrected" and r["memory_id"]:
                d = item["details"]
                vs = {v["version"]: v["original_content"] for v in self.db.query("SELECT version, original_content FROM memory_versions WHERE memory_id=?", (r["memory_id"],))}
                item["before"], item["after"] = vs.get(d.get("from_version")), vs.get(d.get("to_version"))
            out.append(item)
        return out

    def verify_citations(self, evidence: list[Any], *, user_id: str, tenant_id: str = "default") -> dict:
        """Re-check, against the stored data, that every cited quote is still there unchanged.

        ``evidence`` is ``RecallResult.evidence`` (models or dicts). Each item gets one status:
        ``verified`` (quote found at the cited offsets, hash matches, and it also occurs in the retained original
        source, compared with whitespace collapsed because the chunker re-flows line breaks), ``unlocated`` (the excerpt was never a verbatim span, e.g. a rewritten summary), ``memory_missing``,
        ``quote_changed`` (memory text edited or corrupted since the answer), or ``source_mismatch``.
        """
        from .util import sha256

        results = []
        for ev in evidence:
            d = ev if isinstance(ev, dict) else ev.model_dump()
            mid, s, e, h = d.get("memory_id"), d.get("span_start"), d.get("span_end"), d.get("quote_sha256")
            row = self.db.one("SELECT original_content, source_id FROM memories WHERE id=? AND tenant_id=? AND user_id=?", (mid, tenant_id, user_id))
            if not row:
                status = "memory_missing"
            elif s is None or e is None or not h:
                status = "unlocated"
            else:
                quote = row["original_content"][s:e]
                if not quote or sha256(quote) != h:
                    status = "quote_changed"
                else:
                    src = self.db.one("SELECT content FROM sources WHERE id=?", (row["source_id"],))
                    status = "verified" if src and " ".join(quote.split()) in " ".join(src["content"].split()) else "source_mismatch"
            results.append({"memory_id": mid, "source_id": d.get("source_id"), "status": status})
        return {"valid": bool(results) and all(r["status"] == "verified" for r in results),
                "verified": sum(r["status"] == "verified" for r in results), "total": len(results), "results": results}

    def verify_audit_chain(self) -> bool:
        """Recompute the tamper-evident event hash chain."""
        from .util import sha256

        prev = "genesis"
        for r in self.db.query("SELECT * FROM events ORDER BY seq"):
            expect = sha256(f"{prev}|{r['ts']}|{r['tenant_id']}|{r['type']}|{r['memory_id']}|{r['payload']}")
            if r["prev_hash"] != prev or r["hash"] != expect:
                return False
            prev = r["hash"]
        return True

    # ------------------------------------------------------------------ consolidation / reflection / evaluation
    def consolidate(self, *, user_id: str, tenant_id: str = "default", mode: str = "manual", dry_run: bool = False, **scope_kw: Any) -> dict:
        from .consolidation.engine import Consolidator

        scope = self.scope_for(user_id, tenant_id, **scope_kw)
        return Consolidator(self).run(scope, mode=mode, dry_run=dry_run)

    def rollback_consolidation(self, run_id: str, *, user_id: str, tenant_id: str = "default") -> dict:
        from .consolidation.engine import Consolidator

        return Consolidator(self).rollback(run_id, tenant_id=tenant_id, user_id=user_id)

    def graph(self, *, user_id: str, tenant_id: str = "default", as_of: str | None = None, **scope_kw: Any) -> dict:
        """Nodes and edges of the visible relational memory (for viewers)."""
        from .retrieval.graph import build_graph

        g, names = build_graph(self.db, self.scope_for(user_id, tenant_id, **scope_kw), to_ts(as_of) if as_of else None)
        nodes = [{"id": n, "label": names.get(n, n), "degree": g.degree(n)} for n in g.nodes]
        edges = []
        for _a, _b, data in g.edges(data=True):
            for e in data["edges"]:
                edges.append({"source": e.src, "target": e.dst, "predicate": e.predicate, "kind": e.kind, "memory_id": e.memory_id})
        return {"nodes": nodes, "edges": edges}

    def consolidation_runs(self, *, user_id: str, tenant_id: str = "default", limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT id, ts, mode, status, report, rolled_back_at FROM consolidation_runs WHERE tenant_id=? AND user_id=? ORDER BY ts DESC LIMIT ?", (tenant_id, user_id, limit))
        out = []
        for r in rows:
            rep = json.loads(r["report"])
            out.append({"run_id": r["id"], "ts": r["ts"], "mode": r["mode"], "rolled_back_at": r["rolled_back_at"], "created": len(rep.get("created_memory_ids", [])), "near_duplicates": len(rep.get("near_duplicates", [])), "alias_merges": len(rep.get("alias_merges", [])), "clusters": len(rep.get("clusters", [])), "examined": rep.get("examined", 0)})
        return out

    def recent_recalls(self, *, user_id: str, tenant_id: str = "default", limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT id, ts, query, category, strategy, strategies_tried, status, supported, latency_ms, context_tokens, cached FROM retrieval_log WHERE tenant_id=? AND user_id=? ORDER BY ts DESC, rowid DESC LIMIT ?", (tenant_id, user_id, limit))
        return [{**dict(r), "strategies_tried": json.loads(r["strategies_tried"])} for r in rows]

    def usage_by_provider(self) -> list[dict]:
        rows = self.db.query("SELECT provider, model, kind, COUNT(*) AS calls, SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out, SUM(cost) AS cost, AVG(latency_ms) AS mean_latency_ms FROM provider_usage GROUP BY provider, model, kind")
        return [dict(r) for r in rows]

    def enable_latent(self, n_slots: int = 16, backend_factory=None):
        """Turn on the experimental latent-memory retrieval strategy (off by default)."""
        from .latent.index import LatentIndex

        idx = LatentIndex(self, backend_factory=backend_factory, n_slots=n_slots)
        self.recaller.latent = idx
        return idx

    def start_scheduler(self, *, user_id: str, tenant_id: str = "default", interval_seconds: float = 3600.0) -> None:
        from .consolidation.engine import ConsolidationScheduler

        self._scheduler = ConsolidationScheduler(self, user_id, tenant_id, interval_seconds)
        self._scheduler.start()

    def reflect(self, *, user_id: str, tenant_id: str = "default", topic: str | None = None, **scope_kw: Any) -> dict:
        """Deterministic digest: recurring entities/themes, open conflicts, and stale values. No LLM involved."""
        from .consolidation.engine import reflect_report

        return reflect_report(self, self.scope_for(user_id, tenant_id, **scope_kw), topic)

    def evaluate(self, cases: Sequence[dict], *, user_id: str, tenant_id: str = "default", k: int = 5) -> dict:
        """Score this instance on QA cases: [{question, answer?, relevant_memory_ids?, answerable?}]."""
        from .evaluation.runner import evaluate_memory

        return evaluate_memory(self, cases, user_id=user_id, tenant_id=tenant_id, k=k)

    # ------------------------------------------------------------------ admin
    def export(self, *, user_id: str, tenant_id: str = "default") -> dict:
        """All data owned by a user (JSON-serialisable): memories, sources, facts, versions."""
        mems = self.db.query("SELECT * FROM memories WHERE tenant_id=? AND user_id=? AND status='active'", (tenant_id, user_id))
        ids = [m["id"] for m in mems]
        out_mem = []
        for m in mems:
            rec = self._record(m).model_dump()
            rec["versions"] = [dict(v) for v in self.db.query("SELECT version, original_content, changed_at, reason FROM memory_versions WHERE memory_id=? ORDER BY version", (m["id"],))]
            out_mem.append(rec)
        facts = []
        if ids:
            marks = ",".join("?" * len(ids))
            facts = [dict(r) for r in self.db.query(f"SELECT id, memory_id, subject, predicate, object, valid_from, valid_until, recorded_at, retracted_at FROM facts WHERE memory_id IN ({marks})", ids)]
        return {"tenant_id": tenant_id, "user_id": user_id, "exported_at": self.store.now(), "memories": out_mem, "facts": facts}

    def backup(self, dest: str | Path) -> Path:
        return self.db.backup(dest)

    def stats(self, *, tenant_id: str = "default") -> dict:
        def one(sql: str, *p: Any) -> Any:
            return self.db.one(sql, p)[0]

        lat = sorted(r[0] for r in self.db.query("SELECT latency_ms FROM retrieval_log WHERE tenant_id=? AND cached=0", (tenant_id,)))

        def pct(p: float) -> float:
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 3) if lat else 0.0

        by_strategy = {r["strategy"]: r["n"] for r in self.db.query("SELECT strategy, COUNT(*) AS n FROM retrieval_log WHERE tenant_id=? GROUP BY strategy", (tenant_id,))}
        by_cat = {r["category"]: r["n"] for r in self.db.query("SELECT category, COUNT(*) AS n FROM memories WHERE tenant_id=? AND status='active' GROUP BY category", (tenant_id,))}
        usage = self.db.one("SELECT COALESCE(SUM(tokens_in),0) AS tin, COALESCE(SUM(tokens_out),0) AS tout, COALESCE(SUM(cost),0) AS cost, COUNT(*) AS calls FROM provider_usage")
        return {
            "memories": one("SELECT COUNT(*) FROM memories WHERE tenant_id=? AND status='active'", tenant_id),
            "derived_memories": one("SELECT COUNT(*) FROM memories WHERE tenant_id=? AND status='active' AND derived=1", tenant_id),
            "sources": one("SELECT COUNT(*) FROM sources WHERE tenant_id=?", tenant_id),
            "facts": one("SELECT COUNT(*) FROM facts WHERE tenant_id=? AND retracted_at IS NULL", tenant_id),
            "memories_by_category": by_cat,
            "recalls": len(lat) + one("SELECT COUNT(*) FROM retrieval_log WHERE tenant_id=? AND cached=1", tenant_id),
            "recalls_by_strategy": by_strategy,
            "recall_latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": round(lat[-1], 3) if lat else 0.0},
            "mean_context_tokens": round(one("SELECT COALESCE(AVG(context_tokens),0) FROM retrieval_log WHERE tenant_id=?", tenant_id), 1),
            "unsupported_rate": round(one("SELECT COALESCE(AVG(1 - supported),0) FROM retrieval_log WHERE tenant_id=?", tenant_id), 4),
            "query_cache": {"hits": self.recaller.cache_hits, "misses": self.recaller.cache_misses},
            "provider_usage": {"calls": usage["calls"], "tokens_in": usage["tin"], "tokens_out": usage["tout"], "cost": usage["cost"]},
            "embedding_cache_rows": one("SELECT COUNT(*) FROM embeddings"),
            "storage_bytes": Path(self.db.path).stat().st_size if self.db.path != ":memory:" and Path(self.db.path).exists() else 0,
            "schema_version": self.db.schema_version,
            "embedder": self.embedder.name,
        }

    def health(self, *, deep: bool = False) -> dict:
        """Liveness. ``deep=True`` also probes the embedding provider (may make a network call)."""
        ok = self.db.one("SELECT 1")[0] == 1
        out = {"status": "ok" if ok else "error", "schema_version": self.db.schema_version, "audit_chain_valid": self.verify_audit_chain(), "embedder": self.embedder.name, "chat_provider": getattr(self.chat, "name", None), "extractor": self.extractor.name}
        if deep:
            out["embedding"] = self.embedding_info(deep=True)
            if ok and not out["embedding"]["health"]["ok"]:
                out["status"] = "degraded"
        return out


def _to_extracted(f: dict | ExtractedFact) -> ExtractedFact:
    if isinstance(f, ExtractedFact):
        return f
    for key in ("subject", "predicate", "object"):
        if not f.get(key):
            raise ValueError(f"explicit fact missing '{key}'")
    from .ingestion.extract import norm_predicate

    return ExtractedFact(
        subject=str(f["subject"]), predicate=norm_predicate(str(f["predicate"])), object=str(f["object"]),
        valid_from=f.get("valid_from"), valid_until=f.get("valid_until"), precision=None,
        confidence=float(f.get("confidence", 1.0)), excerpt=str(f.get("excerpt", f"{f['subject']} {f['predicate']} {f['object']}")),
        polarity=str(f.get("polarity", "affirmed")), method="explicit",
    )


def _text_date(text: str) -> str | None:
    d = extract_dates(text).valid_from
    return to_ts(d) if d else None


def _flatten(obj: dict, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.extend(_flatten(v, key + "."))
        elif isinstance(v, list):
            out.append((key, ", ".join(str(x) for x in v)))
        else:
            out.append((key, v))
    return out
