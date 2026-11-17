# Implementation Status

_Last updated 2026-11-17. This file lists what works, what is partial, and what is not done. "Done" means implemented **and** covered by passing automated tests._

## Test results

`python -m pytest` → **133 passed** (unit, integration scenarios A–L, API, MCP, SDK, examples, security, regression). `ruff check` clean; `bandit -ll` clean (B608 skipped with justification in `pyproject.toml`). TypeScript SDK: 3 tests pass. Dashboard: `tsc --noEmit` and `next build` pass; a live smoke test (API with API key + seeded data + dashboard pages) returned HTTP 200 on all 10 pages with live data and no key in browser HTML. Benchmark: full run reproduced digest `e6d3630a275a` across runs.

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
6. No encryption at rest; backups are not rewritten on `forget`.
7. Vector search is exact brute force; scale beyond ~10⁵ memories per scope is unmeasured.
8. Benchmark datasets are synthetic and project-authored; no LoCoMo/LongMemEval run; no external system run.
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
