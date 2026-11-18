# MemoraOS Next: repository audit

Phase 0 of the MemoraOS Next specification. Every statement below comes from something run or read in this working tree; where something was not run it says so. Date of audit: 2026-11-18. Branch: `feature/memoraos-next` (from `main` at `0d87348`). Platform: Windows 11, Python 3.14.3, Node 22.

## Baseline commands and their actual results

| Command | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider` (start of session) | 284 passed, 0 failed, 29 s |
| `python -m pytest -q -p no:cacheprovider` (after this work) | 307 passed, 0 failed (304 at the first full run; 3 tests for the statistics helpers were added afterwards; 327 after encryption, ANN, Memory CI options and public-benchmark tests were added) |
| `python -m ruff check src tests benchmarks scripts examples` | All checks passed |
| `python -m bandit -q -r src -ll -c pyproject.toml` | no findings |
| `python -m benchmarks.run` | digest `6a27829d09a1b0b9` unchanged before and after the audit work (it later changed to `c35859a13f53` because of the passage-fallback recency fix, see [NEXT_IMPLEMENTATION_STATUS.md](NEXT_IMPLEMENTATION_STATUS.md)); MemoraOS 100% pooled (saturated, see README) |
| `python scripts/audit_probe.py` | 22 / 23 (last session; the remaining probe needs the LLM extractor) |
| `cd sdk/typescript && npm test` | 3 passed, 0 failed |
| `cd apps/dashboard && npx tsc --noEmit` | clean |
| Wheel build, install into a fresh venv, run from outside the repo | `memoraos 0.2.0`; `MemoryOS.in_memory()` remember/recall works; `memoraos ci run --help` works |
| API integration, MCP, migration tests | included in the 304 (`tests/integration`, `tests/unit` migration and MCP files) |

Not run in this session: the dashboard production build and a live browser session (done in the previous session on the same UI code), and any test against a real LLM or hosted API.

## Existing GitHub issues

| # | Title | State | Status after this work |
|---|---|---|---|
| 1 | LLM-assisted fact extraction | open | The code path exists (`extraction_mode=llm|hybrid`) and is tested with scripted fakes only. No local LLM runtime (Ollama) is available here, so real-provider quality is **unmeasured**. Not closed. |
| 2 | ANN index | open | At audit time: not started. Later: opt-in IVF implemented and measured (recall 0.52-0.93; exact stays default), see [SCALING.md](SCALING.md). |
| 3 | LoCoMo / LongMemEval adapters | open | At audit time: not started. Later: retrieval-only adapters run, see [PUBLIC_BENCHMARKS.md](PUBLIC_BENCHMARKS.md). Answer-accuracy judging is not done. |
| 4 | Encryption at rest | open | At audit time: not started. Later: implemented, see [SECURITY.md](SECURITY.md#encryption-at-rest). |
| 5 | Docker | open | At audit time: not started. Later: implemented and smoke-tested, see [DOCKER.md](DOCKER.md). |

## Component classification

`IV` = IMPLEMENTED_AND_VERIFIED, `IL` = IMPLEMENTED_WITH_LIMITATIONS, `IN` = IMPLEMENTED_BUT_NOT_TESTED, `DN` = DOCUMENTED_BUT_NOT_IMPLEMENTED, `M` = MISSING, `RR` = REQUIRES_REFACTORING, `DD` = DEFERRED_BY_DESIGN.

| Component | Class | Evidence and limits |
|---|---|---|
| SQLite persistence, additive migrations | IV | Migration 2 tested against a real v0.1 database; automatic `.bak-v1` copy. |
| FTS5 / BM25, cosine vector search, RRF | IV | Unit tests and the ablation. Brute-force vector search: **IL**, scale limit unmeasured. |
| Deterministic adaptive router | IV | Tests; real routing table in the README figure. Learned routing: IL (off by default, offline only). |
| Bitemporal facts, history, as-of | IV | Real-date benchmark; out-of-order tests. Relative dates ("last month"), time zones other than UTC and approximate dates: **M**. |
| Contradiction / version-change analysis | IV | Tests and synthetic scenarios. |
| Evidence fusion (typed multi-hop) | IL | Tests and a synthetic scenario; not measured on real multi-hop data. |
| Rule-based extraction | IL | English rules; `plan`/`tier` single-valued gap found and fixed in this work; "The customer plan is X" (no "of"/possessive) yields no fact. |
| LLM extraction | IN | Scripted fakes only. |
| Embedding providers (Ollama, OpenAI-compatible, sentence-transformers) | IL | Interfaces and registry tested; one real neural model (MiniLM-L6-v2) benchmarked in this work, nothing else. |
| Answerability (answer or abstain) | IL | See `docs/NEXT_ANSWERABILITY.md`: refuses 15 of 22 answerable questions it had retrieved evidence for. |
| Consolidation with rollback | IV | Originals asserted intact by tests and the benchmark. |
| Entity resolution | IL | Conservative alias merges only; no split, no entity history, no scope-aware aliases. |
| Latent memory | IL | CPU k-means/slot baseline, labelled experimental. Real Memorilla: **DN** (adapter contract only). |
| Audit hash chain | IL | Tamper-evident, but a database-level attacker can rewrite the whole chain; no signed checkpoints (**M**). |
| REST API, Python SDK, TS SDK, CLI | IV | Integration tests, SDK tests, wheel smoke test. |
| MCP server | IL | 6 tools (remember, recall, correct, forget, history, explain); no propose/review/evaluate tools. |
| Dashboard | IL | Type-checks; 6 pages captured on real data; no lifecycle, change-set, skill or provider pages. |
| Benchmark lab | IL | Synthetic (saturated), real-docs, real-temporal, and now answerability and failure taxonomy. Public datasets (LoCoMo, LongMemEval, ...): **M**. Competitor adapters: **M** (availability probes only, reported as not evaluated). |
| Memory lifecycle states (disputed, archived, expired, ...) | M | Only `active` and deleted-by-forget exist as states. |
| Memory controls (confirm, reject, archive, restore, delete preview) | M | `correct`, `verify`, `forget`, `export` exist. |
| Agent experience and skill memory | M | |
| Memory Change Sets (branch, diff, merge, rollback) | M | |
| Memory CI | IV (new) | Added in this work; see `docs/MEMORY_CI.md`. Automatic triggers: M. |
| Encryption at rest, key rotation | M | Issue #4. |
| ANN index | M | Issue #2. |
| Docker | M | Issue #5. |
| Multimodal ingestion, connectors | M | |
| Agent-framework adapters, .NET client | M | |
| Presets (`local_minimal`, ...) | M | Would have to be backed by measurements. |
| Extra answer statuses (partial, ambiguous, provider unavailable) | M | Not added: they change the public API and the TypeScript SDK. |

## Findings made while auditing (new, verified)

1. **The answer-or-abstain decision, not retrieval, is the main recall bottleneck.** 22 of 46 answerable real-document questions are missed; for 15 of them the section containing the answer *was* retrieved and a guard refused (10 term-coverage, 5 attribute-word); only 1 is a retrieval miss. Classification: `benchmarks/reports/REAL_DOCS_FAILURES.md`.
2. **A neural embedder alone does not fix it.** With MiniLM-L6-v2, strict answerable recall on dev moved 57% to 60%, because the guard is lexical.
3. **A lexical "unknown word" guard would be harmful**: 11 of 30 answerable dev questions contain a word that appears nowhere in the documentation (natural paraphrase), so it was rejected on measurement.
4. **`plan` was multi-valued**, so "current plan" returned both the old and the new plan. Fixed, with a regression test.
5. **The default documents-only fallback can return a stale value** when no fact was extracted ("The customer plan is Professional." then "... Enterprise." answers "Professional"). Not fixed; recorded in the gap analysis.
6. The GitHub repository description still says "97.2% accuracy vs 65-70% for plain RAG". The README documents that the synthetic benchmark is saturated and that MemoraOS is not ahead on real prose. The description needs to change (a suggested text is in `docs/NEXT_IMPLEMENTATION_STATUS.md`); this work did not edit repository metadata.

