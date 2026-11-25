# Implementation Status

_Last updated for v0.2.1. This file lists what works, what is partial, and what is not done. "Done" means implemented **and** covered by passing automated tests._

## v0.2 status

| Area | Status | Notes |
|---|---|---|
| Phase Zero audit, plan, ADRs | ✅ | `V02_REPOSITORY_AUDIT.md`, `V02_IMPLEMENTATION_PLAN.md`, `ADR/0001–0007` |
| Schema migration 2 | ✅ | Additive; tested on a real v0.1 database fixture; automatic `.bak-v1` backup |
| Part 6 semantic extraction | ✅ rules / 🧪 LLM | Negation, corrections, conjunctions, value normalization, spans, `rebuild_facts()`. LLM path (grounded, validated) tested with scripted fakes **only** |
| Part 7 embeddings and retrieval | ✅ interfaces / 🧪 neural | Provider v2, mismatch guard, `reembed`/`rebuild_index`, fusion strategies, entity/exact retrievers, expansion, reranker adapters. Neural embedder/cross-encoder tested with fakes; **not benchmarked**. Optional pieces stay off by default because the ablation showed no gain |
| Part 8.1 evidence fusion | ✅ | Typed path search, validation, bounds, conflicts, trace; benchmarked (50% → 100% on the evidence-fusion scenario when enabled) |
| Spec after Part 8.1 step 7 | ❌ not implemented | The supplied specification was truncated there |
| `audit_probe.py` | 22 / 23 | The remaining probe ("You can reach Priya in Pune these days") requires the LLM extractor; it is not claimed as solved |

## Test results (v0.2)

`python -m pytest` → **358 passed**; `ruff check` clean. The synthetic benchmark digest and the real-document report are regenerated with every release; see `benchmarks/reports/`. The v0.1 text below is retained for history.

## Test results (v0.1)

`python -m pytest` → **135 passed** (unit, integration scenarios A–L, API, MCP, SDK, examples, security, regression). `ruff check` clean; `bandit -ll` clean (B608 skipped with justification in `pyproject.toml`). TypeScript SDK: 3 tests pass. Dashboard: `tsc --noEmit` and `next build` pass; a live smoke test (API with API key + seeded data + dashboard pages) returned HTTP 200 on all 10 pages with live data and no key in browser HTML. Benchmark: full runs reproduce every accuracy figure; the result digest is `89405a04f9a0` for the committed report (it changed from `e6d3630a275a` when a fix to entity noise altered consolidation counts and storage ratios, not accuracy).

## Phases

| Phase | Status | Notes |
|---|---|---|
| 0 Research & architecture | ✅ | [Research](RESEARCH_AND_COMPETITIVE_ANALYSIS.md), [Architecture](ARCHITECTURE.md) (contracts, schema, decisions, risks) |
| 1 Memory foundation | ✅ | SQLite, FTS5/BM25, vector, hybrid RRF, source attribution, restart persistence |
| 2 Adaptive intelligence | ✅ | Router, 9 strategies, temporal, episodic, semantic, graph, fallbacks, observable plans |
| 3 Truth & consolidation | ✅ | Contradictions, reliability, abstention, consolidation, rollback, time travel, hash-chained audit |
| 4 Latent memory research | 🧪 partial | Interface, CPU k-means baseline, information-preservation evaluator, unit tests. **No Memorilla reproduction, no learned module, no benefit claimed** |
| 5 Benchmark & optimisation | ✅ / partial | 15 scenarios, 6 systems + ablation, CIs, digest, regression tests. **External systems not executed.** Learning guard implemented and unit-tested; enabled path has a smoke test but no evidence it improves accuracy |
| 6 Developer ecosystem | ✅ | REST, Python client, TypeScript SDK, MCP, dashboard, examples, docs, CI workflows |

## Spec checklist (first-release definition of done)

| Requirement | Status |
|---|---|
| Core engine local; persistence across restarts | ✅ (scenario F, benchmark) |
| Hybrid retrieval; adaptive routing; temporal memory; evidence attribution | ✅ |
| Contradiction detection; consolidation preserves originals | ✅ (scenarios D, E) |
| Multi-user isolation tested | ✅ (scenario G, API tests, security tests) |
| Unsupported answers handled | ✅ (scenario H; benchmark 0% unsupported-answer rate on this suite) |
| Python SDK, REST API, TypeScript SDK, MCP, dashboard | ✅ |
| Core documentation | ✅ |
| CI pipeline | ✅ defined in `.github/workflows` — **not yet run on GitHub** (no remote repository in this workspace; locally the same commands pass) |
| Benchmark methodology reproducible | ✅ |
| No mandatory paid service | ✅ |

## Known issues and limitations

1. **Paraphrase robustness** (measured): MemoraOS 77.1% vs. 100% plain RAG. Unparsed phrasings ("You can reach P in C these days", "How much does P make?") cause abstention.
2. Rule-based extraction: English only, no coreference/negation/relative dates.
3. Lexical default embedder; neural embedders are adapters, **untested against real servers** (HTTP behaviour is tested with mock transports).
4. A `RerankProvider` interface and `LexicalReranker` exist but are **not wired into the retrieval path**.
5. Storage overhead on very short texts is large (≈351× raw text in the benchmark).
6. Encryption at rest was added after v0.2 as an opt-in (see [SECURITY.md](SECURITY.md)); backups are not rewritten on `forget`.
7. Vector search is exact brute force; scale beyond ~10⁵ memories per scope is unmeasured.
8. Benchmark datasets are synthetic and project-authored; retrieval-only LoCoMo/LongMemEval runs now exist (`benchmarks/public.py`), but no answer-accuracy run and no external system run.
9. Query cache and graph cache are process-local; multi-process deployments share only SQLite state (caches validate against the event sequence).
10. PostgreSQL / external vector / graph / object-storage adapters: **not implemented** (only the interface seams: providers and `Database`).
11. Multimodal ingestion: not implemented (text and JSON only).
12. The MCP server and REST API were smoke-tested with in-process and live clients, but not with a third-party MCP client application.
13. Windows-first development: CI matrix includes Linux but has not been exercised.

## Architectural decisions (see ARCHITECTURE.md for rationale)

SQLite + FTS5; brute-force cosine; NetworkX graph on demand; deterministic routing; extractive answers; bitemporal facts as rows (retract, never overwrite); append-only hash-chained events; API keys hashed with tenant/role binding; hard deletion with a content-free audit stub.

## Next steps

See [ROADMAP.md](ROADMAP.md). First: LLM-assisted extraction measured on the paraphrase scenario; LoCoMo/LongMemEval adapters; executable external baselines.

## Commands

```bash
pip install -e ".[dev,api]"            # install
python -m pytest                       # test
python -m benchmarks.run               # benchmark (writes benchmarks/reports/)
memoraos keys create --tenant default --role admin
memoraos serve                         # API on :8000
cd apps/dashboard && npm install && npm run dev     # dashboard on :3000 (copy .env.example to .env.local)
python examples/basic_memory/main.py   # examples
```


