"""FastAPI REST application. Secure by default: refuses to start without API keys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..engine import MemoryOS, NotFoundError, PermissionDenied
from .auth import ApiKeyStore, Principal

UserId = Field(min_length=1, max_length=200)


class ScopeBody(BaseModel):
    user_id: str = UserId
    agent_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=200)


class RememberBody(ScopeBody):
    text: str = Field(min_length=1, max_length=2_000_000)
    level: Literal["user", "agent", "session", "project", "org"] = "user"
    source_type: Literal["user_statement", "conversation", "document", "structured", "external", "inferred"] = "user_statement"
    origin: str | None = Field(default=None, max_length=500)
    category: Literal["episodic", "semantic", "procedural"] | None = None
    effective_at: str | None = None
    reliability: float | None = Field(default=None, ge=0, le=1)
    verification: Literal["unverified", "verified", "disputed", "hypothesis"] = "unverified"
    metadata: dict[str, Any] | None = None
    facts: list[dict[str, Any]] | None = Field(default=None, max_length=500)


class ConversationBody(ScopeBody):
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class JsonBody(ScopeBody):
    record: dict[str, Any] | list[dict[str, Any]]
    subject: str | None = None


class RecallBody(ScopeBody):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    as_of: str | None = None
    strategy: Literal["exact", "bm25", "vector", "hybrid", "graph", "fusion", "temporal", "episodic", "procedural", "latent", "multistage"] | None = None
    synthesize: bool = False


class CorrectBody(BaseModel):
    user_id: str = UserId
    new_content: str = Field(min_length=1, max_length=2_000_000)
    reason: str | None = Field(default=None, max_length=500)


class CitationsBody(BaseModel):
    user_id: str = UserId
    evidence: list[dict]


class VerifyBody(BaseModel):
    user_id: str = UserId
    status: Literal["unverified", "verified", "disputed", "hypothesis"]


class FeedbackBody(BaseModel):
    recall_id: str
    correct: bool | None = None
    relevance: float | None = Field(default=None, ge=0, le=1)
    comment: str | None = Field(default=None, max_length=1000)


class ConsolidateBody(ScopeBody):
    mode: Literal["manual", "incremental", "dry_run"] = "manual"


class LinkBody(BaseModel):
    user_id: str = UserId
    src_id: str
    dst_id: str
    kind: Literal["causes", "solves", "supersedes", "blocked_by"]


class OutcomeBody(ScopeBody):
    action: str = Field(min_length=1, max_length=2000)
    outcome: Literal["failed", "succeeded"]
    reason: str | None = Field(default=None, max_length=2000)
    evidence_ref: str | None = Field(default=None, max_length=500)


class ReplayBody(BaseModel):
    user_id: str = UserId
    recall_id: str
    exclude: list[str] = Field(default_factory=list, max_length=50)
    leave_one_out: bool = False


def create_app(
    engine: MemoryOS,
    keys: ApiKeyStore | None = None,
    *,
    insecure_no_auth: bool = False,
    reports_dir: Path | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    if keys is None or len(keys) == 0:
        if not insecure_no_auth:
            raise RuntimeError(
                "No API keys configured. Create one with `memoraos keys create --tenant <t>` or pass insecure_no_auth=True for local development only."
            )
    app = FastAPI(title="MemoraOS API", version=__version__, docs_url="/docs", redoc_url=None)
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])
    reports = reports_dir or Path("benchmarks/reports")

    def auth(request: Request, authorization: str | None = Header(default=None)) -> Principal:
        if insecure_no_auth and (keys is None or len(keys) == 0):
            return Principal("default", "admin", ("*",), "insecure")
        token = authorization.split(" ", 1)[1].strip() if authorization and authorization.lower().startswith("bearer ") else None
        p = keys.authenticate(token) if keys else None
        if not p:
            raise HTTPException(401, "invalid or missing API key", headers={"WWW-Authenticate": "Bearer"})
        return p

    def need(role: str):
        def dep(p: Principal = Depends(auth)) -> Principal:
            if not p.can(role):
                raise HTTPException(403, f"this key has role '{p.role}'; '{role}' required")
            return p

        return dep

    def act_as(p: Principal, user_id: str) -> None:
        if not p.may_act_as(user_id):
            raise HTTPException(403, "this key may not act as that user")

    def audit(p: Principal, action: str, target: str | None = None) -> None:
        engine.store.audit(p.tenant_id, p.fingerprint, action, target)

    @app.exception_handler(NotFoundError)
    async def _nf(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": "not found"}, status_code=404)

    @app.exception_handler(PermissionDenied)
    async def _pd(_: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(ValueError)
    async def _ve(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def scope_kw(b: ScopeBody) -> dict:
        return {"agent_id": b.agent_id, "session_id": b.session_id, "project_id": b.project_id}

    # ---- meta ---------------------------------------------------------------------------
    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/v1/system/health")
    def system_health(p: Principal = Depends(need("read"))) -> dict:
        return engine.health()

    @app.get("/v1/stats")
    def stats(p: Principal = Depends(need("read"))) -> dict:
        return engine.stats(tenant_id=p.tenant_id)

    @app.get("/v1/strategies")
    def strategies(p: Principal = Depends(need("read"))) -> list[dict]:
        return engine.strategy_report(p.tenant_id)

    @app.get("/v1/usage")
    def usage(p: Principal = Depends(need("read"))) -> list[dict]:
        return engine.usage_by_provider()

    # ---- write ---------------------------------------------------------------------------
    @app.post("/v1/memories", status_code=201)
    def remember(b: RememberBody, p: Principal = Depends(need("write"))) -> dict:
        act_as(p, b.user_id)
        r = engine.remember(
            b.text, user_id=b.user_id, tenant_id=p.tenant_id, level=b.level, source_type=b.source_type, origin=b.origin,
            category=b.category, effective_at=b.effective_at, reliability=b.reliability, verification=b.verification,
            metadata=b.metadata, facts=b.facts, **scope_kw(b),
        )
        audit(p, "remember", r.memory_ids[0])
        return r.model_dump()

    @app.post("/v1/conversations", status_code=201)
    def conversation(b: ConversationBody, p: Principal = Depends(need("write"))) -> list[dict]:
        act_as(p, b.user_id)
        res = engine.remember_conversation(b.messages, user_id=b.user_id, tenant_id=p.tenant_id, session_id=b.session_id, agent_id=b.agent_id, project_id=b.project_id)
        audit(p, "remember_conversation", str(len(res)))
        return [r.model_dump() for r in res]

    @app.post("/v1/memories/json", status_code=201)
    def remember_json(b: JsonBody, p: Principal = Depends(need("write"))) -> list[dict]:
        act_as(p, b.user_id)
        res = engine.remember_json(b.record, user_id=b.user_id, subject=b.subject, tenant_id=p.tenant_id, **scope_kw(b))
        audit(p, "remember_json", str(len(res)))
        return [r.model_dump() for r in res]

    @app.patch("/v1/memories/{memory_id}")
    def correct(memory_id: str, b: CorrectBody, p: Principal = Depends(need("write"))) -> dict:
        act_as(p, b.user_id)
        rec = engine.correct(memory_id, b.new_content, user_id=b.user_id, tenant_id=p.tenant_id, reason=b.reason)
        audit(p, "correct", memory_id)
        return rec.model_dump()

    @app.post("/v1/memories/{memory_id}/verify")
    def verify(memory_id: str, b: VerifyBody, p: Principal = Depends(need("write"))) -> dict:
        act_as(p, b.user_id)
        engine.verify(memory_id, b.status, user_id=b.user_id, tenant_id=p.tenant_id)
        audit(p, "verify", memory_id)
        return {"memory_id": memory_id, "verification": b.status}

    @app.delete("/v1/memories/{memory_id}")
    def forget(memory_id: str, user_id: str = Query(min_length=1, max_length=200), p: Principal = Depends(need("write"))) -> dict:
        act_as(p, user_id)
        n = engine.forget(memory_id, user_id=user_id, tenant_id=p.tenant_id)
        audit(p, "forget", memory_id)
        return {"deleted": n}

    @app.delete("/v1/users/{user_id}")
    def forget_user(user_id: str, p: Principal = Depends(need("admin"))) -> dict:
        act_as(p, user_id)
        n = engine.forget(user_id=user_id, tenant_id=p.tenant_id, everything=True)
        audit(p, "forget_user", user_id)
        return {"deleted": n}

    @app.post("/v1/feedback")
    def feedback(b: FeedbackBody, p: Principal = Depends(need("write"))) -> dict:
        row = engine.db.one("SELECT tenant_id FROM retrieval_log WHERE id=?", (b.recall_id,))
        if not row or row["tenant_id"] != p.tenant_id:
            raise HTTPException(404, "not found")
        engine.feedback(b.recall_id, correct=b.correct, relevance=b.relevance, comment=b.comment)
        return {"ok": True}

    @app.post("/v1/consolidate")
    def consolidate(b: ConsolidateBody, p: Principal = Depends(need("write"))) -> dict:
        act_as(p, b.user_id)
        audit(p, "consolidate", b.user_id)
        return engine.consolidate(user_id=b.user_id, tenant_id=p.tenant_id, mode="manual" if b.mode == "dry_run" else b.mode, dry_run=b.mode == "dry_run")

    @app.post("/v1/consolidate/{run_id}/rollback")
    def rollback(run_id: str, user_id: str = Query(min_length=1), p: Principal = Depends(need("write"))) -> dict:
        act_as(p, user_id)
        audit(p, "consolidation_rollback", run_id)
        return engine.rollback_consolidation(run_id, user_id=user_id, tenant_id=p.tenant_id)

    # ---- read ----------------------------------------------------------------------------
    @app.post("/v1/recall")
    def recall(b: RecallBody, p: Principal = Depends(need("read"))) -> dict:
        act_as(p, b.user_id)
        res = engine.recall(b.query, user_id=b.user_id, tenant_id=p.tenant_id, top_k=b.top_k, as_of=b.as_of, strategy=b.strategy, synthesize=b.synthesize, **scope_kw(b))
        audit(p, "recall", res.recall_id)
        return res.model_dump()

    def scope_q(user_id: str = Query(min_length=1, max_length=200), agent_id: str | None = None, session_id: str | None = None, project_id: str | None = None) -> dict:
        return {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "project_id": project_id}

    @app.get("/v1/memories")
    def list_memories(s: dict = Depends(scope_q), category: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), p: Principal = Depends(need("read"))) -> list[dict]:
        act_as(p, s["user_id"])
        return [m.model_dump() for m in engine.list_memories(tenant_id=p.tenant_id, category=category, limit=limit, offset=offset, **s)]

    @app.get("/v1/memories/{memory_id}")
    def get_memory(memory_id: str, s: dict = Depends(scope_q), p: Principal = Depends(need("read"))) -> dict:
        act_as(p, s["user_id"])
        return engine.get(memory_id, tenant_id=p.tenant_id, **s).model_dump()

    @app.get("/v1/memories/{memory_id}/history")
    def memory_history(memory_id: str, s: dict = Depends(scope_q), p: Principal = Depends(need("read"))) -> dict:
        act_as(p, s["user_id"])
        return engine.history(memory_id, tenant_id=p.tenant_id, **{k: v for k, v in s.items()})

    @app.get("/v1/history")
    def value_history(subject: str, predicate: str, s: dict = Depends(scope_q), p: Principal = Depends(need("read"))) -> dict:
        act_as(p, s["user_id"])
        return engine.history(subject=subject, predicate=predicate, tenant_id=p.tenant_id, **s)

    @app.post("/v1/verify-citations")
    def verify_citations(b: CitationsBody, p: Principal = Depends(need("read"))) -> dict:
        return engine.verify_citations(b.evidence, user_id=b.user_id, tenant_id=p.tenant_id)

    @app.get("/v1/explain/{recall_id}")
    def explain(recall_id: str, user_id: str = Query(min_length=1), p: Principal = Depends(need("read"))) -> dict:
        act_as(p, user_id)
        return engine.explain(recall_id, user_id=user_id, tenant_id=p.tenant_id)

    @app.post("/v1/links", status_code=201)
    def link_memories(b: LinkBody, p: Principal = Depends(need("write"))) -> dict:
        act_as(p, b.user_id)
        return engine.link(b.src_id, b.dst_id, b.kind, user_id=b.user_id, tenant_id=p.tenant_id)

    @app.get("/v1/lineage/{memory_id}")
    def lineage(memory_id: str, user_id: str = Query(min_length=1), direction: Literal["up", "down", "both"] = "both", max_depth: int = Query(5, ge=1, le=20), p: Principal = Depends(need("read"))) -> dict:
        act_as(p, user_id)
        return engine.lineage(memory_id, user_id=user_id, tenant_id=p.tenant_id, direction=direction, max_depth=max_depth)

    @app.post("/v1/outcomes", status_code=201)
    def remember_outcome(b: OutcomeBody, p: Principal = Depends(need("write"))) -> dict:
        act_as(p, b.user_id)
        r = engine.remember_outcome(b.action, b.outcome, user_id=b.user_id, reason=b.reason, evidence_ref=b.evidence_ref, tenant_id=p.tenant_id, **scope_kw(b))
        audit(p, "remember_outcome", r.memory_ids[0])
        return r.model_dump()

    @app.get("/v1/outcome-warnings")
    def outcome_warnings(query: str = Query(min_length=1, max_length=2000), user_id: str = Query(min_length=1, max_length=200), limit: int = Query(5, ge=1, le=50), p: Principal = Depends(need("read"))) -> list[dict]:
        act_as(p, user_id)
        return engine.outcome_warnings(query, user_id=user_id, tenant_id=p.tenant_id, limit=limit)

    @app.post("/v1/replay")
    def replay(b: ReplayBody, p: Principal = Depends(need("write"))) -> dict:
        act_as(p, b.user_id)
        return engine.replay(b.recall_id, user_id=b.user_id, tenant_id=p.tenant_id, exclude=b.exclude, leave_one_out=b.leave_one_out)

    @app.get("/v1/facts")
    def facts(s: dict = Depends(scope_q), as_of: str | None = None, p: Principal = Depends(need("read"))) -> list[dict]:
        act_as(p, s["user_id"])
        return [f.model_dump() for f in engine.facts(tenant_id=p.tenant_id, as_of=as_of, **{k: v for k, v in s.items() if k != "user_id"}, user_id=s["user_id"])]

    @app.get("/v1/contradictions")
    def contradictions(s: dict = Depends(scope_q), p: Principal = Depends(need("read"))) -> list[dict]:
        act_as(p, s["user_id"])
        return [c.model_dump() for c in engine.contradictions(tenant_id=p.tenant_id, **s)]

    @app.get("/v1/snapshot")
    def snapshot(as_of: str, s: dict = Depends(scope_q), p: Principal = Depends(need("read"))) -> dict:
        act_as(p, s["user_id"])
        return engine.snapshot(as_of, tenant_id=p.tenant_id, **s)

    @app.get("/v1/changes")
    def changes(since: str, user_id: str = Query(min_length=1), until: str | None = None, p: Principal = Depends(need("read"))) -> list[dict]:
        act_as(p, user_id)
        return engine.changes(since, until, user_id=user_id, tenant_id=p.tenant_id)

    @app.get("/v1/graph")
    def graph(s: dict = Depends(scope_q), as_of: str | None = None, p: Principal = Depends(need("read"))) -> dict:
        act_as(p, s["user_id"])
        return engine.graph(tenant_id=p.tenant_id, as_of=as_of, **s)

    @app.get("/v1/consolidation/runs")
    def runs(user_id: str = Query(min_length=1), p: Principal = Depends(need("read"))) -> list[dict]:
        act_as(p, user_id)
        return engine.consolidation_runs(user_id=user_id, tenant_id=p.tenant_id)

    @app.get("/v1/recalls")
    def recalls(user_id: str = Query(min_length=1), limit: int = Query(50, ge=1, le=500), p: Principal = Depends(need("read"))) -> list[dict]:
        act_as(p, user_id)
        return engine.recent_recalls(user_id=user_id, tenant_id=p.tenant_id, limit=limit)

    @app.post("/v1/reflect")
    def reflect(b: ScopeBody, topic: str | None = None, p: Principal = Depends(need("read"))) -> dict:
        act_as(p, b.user_id)
        return engine.reflect(user_id=b.user_id, tenant_id=p.tenant_id, topic=topic, **scope_kw(b))

    @app.get("/v1/export")
    def export(user_id: str = Query(min_length=1), p: Principal = Depends(need("read"))) -> dict:
        act_as(p, user_id)
        audit(p, "export", user_id)
        return engine.export(user_id=user_id, tenant_id=p.tenant_id)

    @app.get("/v1/benchmarks")
    def benchmarks(p: Principal = Depends(need("read"))) -> list[dict]:
        out = []
        if reports.exists():
            for f in sorted(reports.glob("*.json")):
                try:
                    out.append(json.loads(f.read_text(encoding="utf-8")))
                except ValueError:
                    continue
        return out

    return app
