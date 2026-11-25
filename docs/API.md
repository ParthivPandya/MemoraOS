# Public API reference

Everything is scoped by `user_id` (and optional `tenant_id`, `agent_id`, `session_id`, `project_id`). Memory `level` is one of `user` (default), `session`, `agent`, `project`, `org`.

## Python (`memoraos.MemoryOS`)

```python
from memoraos import MemoryOS
memory = MemoryOS.local()                    # ./.memoraos  (or MemoryOS.local("path") / MemoryOS.in_memory())
```

| Method | Purpose |
|---|---|
| `remember(text, *, user_id, tenant_id="default", level="user", source_type="user_statement", origin=None, category=None, effective_at=None, reliability=None, verification="unverified", metadata=None, facts=None, extract=True)` → `RememberResult` | Store text; returns memory ids, source id, `duplicate_of`, `facts_recorded`, **open `conflicts`**, `redactions` |
| `remember_conversation(messages, *, user_id, session_id=None, …)` | Chat transcript → episodic memories (assistant turns stored as low-reliability, no facts) |
| `remember_json(record, *, user_id, subject=None)` | Structured records; `{subject, predicate, object/value, valid_from?}` become facts |
| `ingest_document(path, *, user_id)` | Copy a text file into `<data_dir>/sources/` and chunk it |
| `recall(query, *, user_id, top_k=None, as_of=None, strategy=None, synthesize=False, use_cache=True)` → `RecallResult` | Answer with evidence; see below |
| `what_did_you_know(query, as_of, …)` | Alias of `recall(as_of=…)` |
| `explain(recall_id, *, user_id)` | Strategy plan, attempts, notes, timeline, contradictions for a past recall |
| `feedback(recall_id, correct=…, relevance=…)`, `strategy_report()` | Outcome tracking for adaptive routing |
| `reflect(*, user_id, topic=None)` | Deterministic digest: recurring entities/terms, open conflicts, version changes |
| `consolidate(*, user_id, mode="manual"\|"incremental", dry_run=False)`, `rollback_consolidation(run_id)`, `start_scheduler(...)` | Consolidation |
| `correct(memory_id, new_content, *, user_id, reason=None)` | New version; old facts retracted |
| `verify(memory_id, "verified"\|"disputed"\|"unverified"\|"hypothesis", *, user_id)` | Adjust source reliability (`hypothesis` marks an unchecked guess: lower reliability, flagged on recall) |
| `verify_citations(evidence, *, user_id)` → `dict` | Re-find each cited quote in its stored source; per-item status `verified` / `unlocated` / `quote_changed` / `source_mismatch` / `memory_missing` ([CITATIONS.md](CITATIONS.md)) |
| `remember_outcome(action, outcome, *, user_id, reason=None, evidence_ref=None)`, `outcome_warnings(query, *, user_id, limit=5)` | Record a failed/succeeded attempt; list recorded failures that match a planned action ([AGENT_WORKFLOW.md](AGENT_WORKFLOW.md)) |
| `link(src_id, dst_id, kind, *, user_id)`, `unlink(...)`, `lineage(memory_id, *, user_id, direction="both", max_depth=5)`, `why(recall_id, *, user_id)` | Explicit causal links (`causes`, `solves`, `supersedes`, `blocked_by`) and the chain around a memory; nothing is inferred ([CAUSAL_AND_REPLAY.md](CAUSAL_AND_REPLAY.md)) |
| `replay(recall_id, *, user_id, exclude=(), leave_one_out=False)` | Re-run a past recall on a temporary copy with chosen memories removed |
| `sleep(...)` | Opt-in maintenance pass ([CAUSAL_AND_REPLAY.md](CAUSAL_AND_REPLAY.md)) |
| `forget(memory_id=None, *, user_id, everything=False)` | Hard delete (+ derived summaries, logs) |
| `history(memory_id)` / `history(subject=, predicate=)` | Version/event history, or value timeline |
| `snapshot(as_of)`, `changes(since, until)` | Time travel and change log with before/after |
| `facts()`, `contradictions()`, `graph()`, `get()`, `list_memories()` | Inspection |
| `export(user_id)`, `backup(path)`, `stats()`, `health()`, `verify_audit_chain()` | Admin |
| `evaluate(cases, *, user_id, k=5)` | Score QA cases (accuracy, Recall@k, MRR, nDCG, unsupported rate…) |
| `enable_latent(n_slots=16)` | 🧪 optional latent strategy |

`RecallResult`: `answer`, `status` (`answered` / `conflict` / `insufficient_evidence`), `supported`, `strategy`, `strategies_tried`, `fallback_used`, `evidence[]` (memory id, source id, excerpt, kind, source type, reliability, verification, effective date, flags), `timeline[]`, `contradictions[]`, `confidence` (separate signals), `plan` (category, scores, reasons), `flags`, `latency_ms`, `context_tokens`, `as_of`, `cached`; `render_context()` returns evidence wrapped as untrusted data for LLM prompts.

Errors: `ValueError` (invalid input), `NotFoundError` (missing or not visible), `PermissionDenied` (visible but not yours to modify).

## REST (`memoraos serve`)

Authentication: `Authorization: Bearer <key>`. Interactive docs at `/docs`. Role: R = read, W = write, A = admin.

| Method & path | Role | Notes |
|---|---|---|
| `GET /v1/health` | none | liveness |
| `POST /v1/memories` | W | body = `RememberBody` (text, user_id, level, source_type, effective_at, facts, …) |
| `POST /v1/conversations`, `POST /v1/memories/json` | W | |
| `PATCH /v1/memories/{id}` | W | correct |
| `POST /v1/memories/{id}/verify` | W | `status`: `unverified` / `verified` / `disputed` / `hypothesis` |
| `POST /v1/verify-citations` | R | `{user_id, evidence[]}` → `{valid, verified, total, results[]}` |
| `POST /v1/outcomes` | W | `{user_id, action, outcome: failed\|succeeded, reason?, evidence_ref?}` |
| `GET /v1/outcome-warnings?query=&user_id=&limit=` | R | recorded failures matching `query` |
| `POST /v1/links` | W | `{user_id, src_id, dst_id, kind}` |
| `GET /v1/lineage/{memory_id}?user_id=&direction=&max_depth=` | R | causal nodes and edges |
| `POST /v1/replay` | R | `{user_id, recall_id, exclude?, leave_one_out?}`; runs on a temporary copy |
| `DELETE /v1/memories/{id}?user_id=` | W | forget |
| `DELETE /v1/users/{user_id}` | A | forget everything the user owns |
| `POST /v1/recall` | R | |
| `GET /v1/explain/{recall_id}` | R | |
| `POST /v1/feedback` | W | `{recall_id, correct?, relevance?}` |
| `POST /v1/consolidate`, `POST /v1/consolidate/{run}/rollback` | W | `mode`: manual / incremental / dry_run |
| `GET /v1/memories`, `/v1/memories/{id}`, `/v1/memories/{id}/history` | R | |
| `GET /v1/history?subject=&predicate=`, `/v1/facts`, `/v1/contradictions`, `/v1/snapshot?as_of=`, `/v1/changes?since=`, `/v1/graph` | R | |
| `GET /v1/consolidation/runs`, `/v1/recalls`, `/v1/strategies`, `/v1/usage`, `/v1/stats`, `/v1/system/health`, `/v1/benchmarks` | R | dashboard data |
| `POST /v1/reflect`, `GET /v1/export` | R | |

Status codes: 401 bad/missing key, 403 role/user restriction, 404 not found (also for other tenants' ids), 422 validation.

## Clients

- Python: `from memoraos.client import MemoraClient; MemoraClient("http://127.0.0.1:8000", key, user_id="u1")`. Besides the basics it has `verify`, `verify_citations`, `remember_outcome`, `outcome_warnings`, `link`, `lineage` and `replay`.
- TypeScript: `sdk/typescript` (`import { MemoraClient } from "@memoraos/sdk"`), methods `remember`, `recall`, `correct`, `forget`, `history`, `explain`, `consolidate`, `feedback`, `export`, `stats`, `verify`, `verifyCitations`, `rememberOutcome`, `outcomeWarnings`, `link`, `lineage`, `replay`. Both clients are covered by tests against fake/in-process servers, not by a long-running deployment.
- Not wrapped by either client: `/v1/conversations`, `/v1/memories/json`, `/v1/snapshot`, `/v1/changes`, `/v1/graph` and the dashboard data routes.

## MCP (`memoraos mcp`, set `MEMORAOS_USER_ID`)

JSON-RPC 2.0 over stdio. Tools: `memora_remember`, `memora_recall`, `memora_outcome`, `memora_warnings`, `memora_correct`, `memora_forget`, `memora_history`, `memora_link`, `memora_lineage`, `memora_replay`, `memora_explain` (see [MCP.md](MCP.md)). The server acts as exactly one configured user; a `user_id` argument supplied by the model is ignored. Example client config:

```json
{ "mcpServers": { "memoraos": { "command": "memoraos", "args": ["mcp"], "env": { "MEMORAOS_USER_ID": "user_001" } } } }
```

## Providers

```python
from memoraos import MemoryOS
from memoraos.providers import OllamaEmbedder, OpenAICompatChat

memory = MemoryOS.local(
    embedder=OllamaEmbedder("nomic-embed-text"),                       # or any EmbeddingProvider
    chat=OpenAICompatChat("llama3.1", "http://localhost:11434/v1"),   # optional: routing assist + answer phrasing
)
```

`FallbackEmbedder([...])` / `FallbackChat([...])` try providers in order. Embedders in one chain must produce the **same dimension** (a mismatching provider is skipped, never mixed into the index).

Providers support timeouts, retries with backoff and `Retry-After`, fallback chains, availability checks (`OllamaEmbedder.is_available()`), and token/cost tracking via `usage_sink=memory.record_usage`. **Changing the embedder** re-embeds lazily (vectors are stored per model).
