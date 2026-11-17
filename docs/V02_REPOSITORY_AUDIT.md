# v0.2 Repository Audit

_Audited 2026-11-17 against commit `b64f173` plus the uncommitted working tree. Every row is backed by source inspection, a test, or a runtime probe (`scripts/audit_probe.py`). README claims were not accepted as evidence._

## 1. Actual baseline

| Check | Result |
|---|---|
| `python -m pytest` | **137 passed** (135 existing + 2 regression tests added during this audit) |
| `ruff check src tests benchmarks examples scripts` | clean |
| `bandit -r src -ll` | clean (B608 skipped with justification) |
| Benchmark (`python -m benchmarks.run`) | 97.2% pooled accuracy for MemoraOS; digest `89405a04f9a0`; **unchanged** by the fixes below |
| TypeScript SDK `npm test` / dashboard `tsc` + `next build` | pass |
| GitHub Actions, last push (`b64f173`) | **CI failed** (`python (windows-latest, 3.10)`: `test_temporal_memory`); the previous push passed. See finding F1. |
| **Spec probe suite (`audit_probe.py`)** | **8 / 23 pass** on the v0.1 engine (baseline). **After v0.2: 22 / 23**; the last, "You can reach Priya in Pune these days", needs the LLM extractor and is not claimed as solved |

_Baseline numbers above describe the audit-time v0.1 state. For the v0.2 outcome see `IMPLEMENTATION_STATUS.md` and `CHANGELOG.md`._

Source size: 5,133 lines in `src/memoraos`; largest modules `engine.py` (604), `recall.py` (535), `consolidation/engine.py` (331).

## 2. Findings that change the plan

**F1. Intermittent wrong "current value" on coarse clocks (confirmed bug, fixed).** The timeline sorted by `(effective time, recorded_at, id)` and `id` is random. On Windows the clock ticks about every 15 ms, so two facts stored back-to-back share `recorded_at`, and the random id decided which was "latest". CI caught it as a flaky failure. Fixes: stable sort on insertion order (`truth/timeline.py`), strictly monotonic system time (`Store.now()`), and a single time source for "now" in recall/history/changes. Tests: `test_equal_timestamps_keep_insertion_order`, `test_system_time_is_strictly_increasing_even_on_a_frozen_clock`. Benchmark digest unchanged.

**F2. Confidently wrong multi-hop answer (open).** The spec's own example, *"Which Azure region is used by the project Alice manages?"* with `Alice manages Project Atlas` / `Project Atlas uses Azure Functions` / `Azure Functions is deployed in West Europe`, returns `answered | exact | 'Project Atlas'`. The slot matcher sees `manages` ≈ `leads` and returns the first hop as if it answered a region question. Nothing checks that the answer *type* matches the question. This is the most serious defect found, because it is a wrong answer with status `answered`.

**F3. Negation is stored as the opposite fact (open).** `I do not use Angular.` yields the fact `user uses Angular`; `recall("What do I use?")` answers `Angular`.

**F4. Corrections are ignored (open).** `Correction: my salary is actually 30 LPA.` produces no fact (the `Correction:` prefix defeats every pattern), so recall still answers `28 LPA`.

**F5. Conjunctions corrupt the object (open).** A single sentence that joins two "works at" clauses with "and" yields one fact whose object swallows the second clause, so the second person's employer cannot be recalled on its own.

**F6. No value normalization (open).** `32 LPA`, `32 lakhs annually`, `32 lakh rupees` and `₹32 lakh per annum` become four distinct canonical forms. With document sources, the second is reported as a **false conflict**. The only reason it looks fine for user statements is the "later self-report supersedes" rule, which hides the problem.

**F7. Plain `the X is Y` statements are not extracted.** `The budget is 5 lakh.` / `The budget is 7 lakh.` produce no facts, so the update is invisible to the truth engine.

**F8. Metadata the spec requires is not persisted.** No embedding provider/version/status columns, no `extraction_method` or source span on facts, no extraction-attempt log, no configurable fusion.

## 3. Component audit

Classification: **V** IMPLEMENTED_AND_VERIFIED · **I** IMPLEMENTED_BUT_INCOMPLETE · **D** DOCUMENTED_BUT_NOT_IMPLEMENTED · **N** NOT_IMPLEMENTED · **R** REQUIRES_REFACTORING. Risk is the risk of changing it.

| Component | Current implementation | Identified limitation | Required change | Class | Risk |
|---|---|---|---|---|---|
| Ingestion | `engine.remember*`: redact, chunk (800/100), classify, dedupe by content hash, embed with cache | Facts extracted per chunk with no source span; one extractor, no provider seam | Route through a `MemoryExtractor` with spans, method and attempts | I | Medium |
| Semantic extraction | `ingestion/extract.py`: ~25 verb rules, possessive/`my`/`of` forms, dates | F3, F4, F5, F7; paraphrase and synonym coverage is lexical; `EntityExtractor` only adds entity names, never facts | Typed schema, provider abstraction, normalizer, validation, safety (Part 6) | I / R | **High** (touches every fact) |
| Entity resolution | `norm_entity`; conservative alias merges in consolidation (`parth` → `parth pandya`) | No resolution at query time beyond aliases; no alias provenance beyond `run_id` | Reuse aliases in query expansion and fusion | I | Low |
| Importance | `Consolidator._importance` (access, mentions, facts, recency) | Computed only at consolidation; never used by retrieval or lifecycle | Expose as a ranking prior, optional | I | Low |
| Temporal engine | `truth/timeline.py` bitemporal runs, 6-rule resolution, as-of reads | F1 (fixed); date-only precision; relative dates unsupported | Keep; add value-aware equality so units don't create false conflicts | V (after F1) | Medium |
| Persistent store | SQLite WAL, versioned migrations (v1), online backup, hash-chained events | Single migration; no v0.1→v0.2 test fixture | Migration 2 + test against a real v0.1 file | V | Medium |
| Semantic indexing | Brute-force cosine over cached NumPy matrix; embeddings keyed `(content_hash, model)` | Only `model`/`dim` recorded; provider/version/normalization/status missing; no re-embed workflow beyond lazy backfill | Metadata columns, explicit rebuild, mixed-model guard (Part 7.1) | I | Medium |
| Embedding providers | `HashingEmbedder`, `OllamaEmbedder`, `OpenAICompatEmbedder`, fallback chain (HTTP tested with mocks only) | Interface is `embed()` + `dim`; no `get_model_info`, `health_check`; no Sentence-Transformers adapter; never run against a real server | `EmbeddingProvider` v2 (backward compatible) | I | Low |
| Retrieval | FTS5 BM25, vector, RRF hybrid (`k` configurable), graph, episodic, procedural, exact, temporal | Fusion strategy/weights not configurable; no entity retriever, no exact identifier retriever | Configurable weighted RRF + two retrievers (Part 7.2) | I | Medium |
| Query expansion | None. Predicate synonyms exist only inside slot matching | Probes: `How much does Priya make?` and `You can reach Priya in Pune` abstain | Expansion with original preserved (Part 7.3) | N | Medium |
| Reranking | `RerankProvider` + `LexicalReranker` classes exist and are constructed in the engine | **Never called by recall** (grep-verified) | Wire as optional stage, benchmark against none (Part 7.4) | D | Low |
| Adaptive router | `routing/router.py`, deterministic scores, cost-aware, fallbacks, guarded learning (off by default) | Router cannot decompose questions; learning path has only a smoke test, no evidence it improves accuracy | Add decomposition signal for fusion | V / I | Medium |
| Evidence fusion | `graph` strategy: shortest path between entities named in the question | **F2.** Cannot follow *"the project Alice manages"* to a region; no answer-type check; no inference-step validation | Decompose, bounded subgraph, validated steps (Part 8) | D / N | **High** |
| Truth engine | Contradictions, reliability margin, support check, abstention | F6 false conflicts; `Contradiction` is value-string based | Compare canonical values, not strings | I | Medium |
| Lifecycle / consolidation | Dedup links, aliases, derived summaries, rollback, incremental watermark | Summary quality is extractive and only unit-tested for safety | None this release | V | Low |
| Confidence | Five separate signals plus route confidence | Calibrated nowhere; `retrieval_relevance` is heuristic | Document as uncalibrated; add extraction method to evidence | I | Low |
| Feedback / evaluation | `feedback()`, `strategy_report()`, `evaluate()`, benchmark lab | Benchmark is synthetic; paraphrase scenario is the honest weak spot | New scenarios for Parts 6–8 with before/after | V | Low |
| Isolation | Single visibility clause, scope levels, key-bound tenants and roles, tests | Project/org membership trusted to caller | None | V | Low |
| API / SDKs / MCP | FastAPI (31 routes), Python client, TS SDK, MCP stdio (6 tools) | New v0.2 metadata not exposed | Expose extraction method/spans in evidence | V | Low |
| Dashboard | 10 pages, server-side API key, live data, screenshots | No view of extraction method or fusion steps | Show fusion steps in playground | V | Low |
| Observability | `retrieval_log`, `explain()`, `stats()`, `provider_usage` | No extraction or embedding health stats | Add counters (attempts, rejects, fallbacks) | I | Low |
| Security | Redaction, injection flags, untrusted rendering, hashed keys | An LLM extractor is a new injection surface | Treat source text as data, validate output against source, no tool use (ADR-0003) | I | **High** |
| Benchmarks | 15 scenarios, CIs, digest, ablation | Does not measure extraction paraphrase normalization or fusion | Add scenarios | V | Low |
| CI | 3 jobs, Python 3.10/3.12/3.13 × ubuntu/windows | **Failing on latest push** (F1) | Re-run after fix | I | Low |
| Documentation | Full doc set | Several numbers were from a single noisy timing run (corrected in this audit) | Keep numbers tied to the committed report | V | Low |

## 4. What this means for scope

The spec's critical priorities (Parts 6, 7, 8) are all genuinely needed: probe results show real wrong answers, not cosmetic gaps. The probe suite becomes the acceptance test for v0.2, and the benchmark gets new scenarios so improvement (or lack of it) is measured with the same harness as v0.1.

**Spec coverage note.** The specification supplied for this work ends mid-sentence at Part 8.1 step 7 ("Validate each inference step"). Parts 8.2 onward, and any later parts (for example agent isolation, lifecycle, calibration, API changes), were not provided and are **not** planned here. See the plan for what is in and out of scope.
