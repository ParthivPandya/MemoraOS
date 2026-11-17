# v0.2 Implementation Plan

Companion to [V02_REPOSITORY_AUDIT.md](V02_REPOSITORY_AUDIT.md) and [V02_ARCHITECTURE.md](V02_ARCHITECTURE.md).

## Scope

The specification provided ends mid-sentence at Part 8.1, step 7. **In scope** is everything it fully specifies: Phase Zero (audit and design), Part 6 (semantic extraction), Part 7 (embedding and retrieval), and Part 8.1 (evidence fusion stages). **Out of scope until the rest of the specification is supplied:** anything the missing parts may define (for example agent access and isolation changes, lifecycle management, confidence calibration, API/MCP/SDK changes, observability additions). Nothing outside the provided text is implemented speculatively.

## Acceptance criteria

1. `scripts/audit_probe.py` is the executable acceptance suite. Baseline **8/23**. Target: every probe passes except those that need an LLM, which must pass with a scripted fake LLM and be reported as "requires LLM" for the deterministic path.
2. A real **v0.1 database file** (created by the v0.1 code, committed as a test fixture) migrates to v0.2 with all memories, facts, embeddings and events intact, and the audit hash chain still verifies.
3. No existing benchmark scenario regresses; new scenarios are added and results are reported **including any that MemoraOS fails**.
4. `pytest`, `ruff`, `bandit` clean; coverage for every new module.
5. No default behavior requires a network call or key.

## Work packages (ordered by dependency)

| # | Package | Key deliverables | Tests |
|---|---|---|---|
| 0 | Clock/ordering fix (F1) | Done in the audit | 2 regression tests |
| 1 | Migration 2 | Additive columns on `facts`/`embeddings`; `embedding_models`, `extraction_attempts` tables | v0.1 fixture migration test |
| 2 | Structured extraction | `extraction/` package: typed schema, value normalizer (lakh/crore/LPA/currency/period), `MemoryExtractor`, rules extractor with negation, corrections, conjunctions, bare attributes, source spans | paraphrase, negation, correction, conjunction, numeric-change, span-verification tests |
| 3 | LLM extraction | `LLMExtractor` over any `ChatProvider`: grounded-output validation, retries, attempt log, deterministic fallback, injection handling | fake-LLM tests incl. malicious outputs |
| 4 | Embedding v2 | `EmbeddingProvider` base with `embed_text/embed_batch/get_model_info/get_embedding_dimension/health_check`; persisted metadata; model registry; `reembed()`; Sentence-Transformers adapter (optional) | mixed-model guard, re-embed, health tests |
| 5 | Retrieval | Configurable weighted RRF; entity and exact-identifier retrievers; query expansion (originals preserved); optional reranker stage + cross-encoder/HTTP adapters | fusion math, expansion invariants, rerank ordering |
| 6 | Evidence fusion | `fusion/`: question decomposition, typed path search over a bounded subgraph, step validation (existence, direction, time, conflicts), deduplication, trace in `explain()` | spec example, conflicts, cycles, expired relations, bounded size |
| 7 | Router + answer-type guard | `fusion` strategy; answer-type check that stops F2-style wrong answers from `exact` | routing tests, F2 regression |
| 8 | Benchmarks | New scenarios (paraphrase normalization, multi-hop fusion, negation/correction); rerank ablation; before/after table | digest + regression guard |
| 9 | Docs and release | README/CHANGELOG/status, version 0.2.0, figures regenerated | doc consistency check |

## Compatibility rules

- Migrations are additive (`ALTER TABLE ... ADD COLUMN` with defaults, new tables). No column is dropped or renamed.
- Public method signatures keep working; new parameters are keyword-only with defaults. `ExtractedFact` gains optional fields only.
- Legacy providers exposing only `name`, `dim`, `embed()` keep working through an adapter.
- v0.1 facts keep their `object_key`; the new normalized keys apply to new facts. `MemoryOS.rebuild_facts()` re-derives facts from preserved originals (old facts are retracted, never deleted) so users can opt in to new normalization for old data.

## Risks

| Risk | Mitigation |
|---|---|
| Value normalization merges facts that differ | Equality needs entity + predicate + value + currency + period; unknown units never merge; property tests |
| Normalizer changes break v0.1 benchmark results | Benchmark guard: any regression blocks the change |
| LLM extractor injects fabricated facts | Facts must quote a verbatim span of the source; rejected otherwise (ADR-0003) |
| Fusion returns plausible but wrong chains | Every step must be a stored, valid fact; ambiguity and conflict are reported, not resolved (ADR-0006) |
| Optional dependencies (sentence-transformers) not installable in CI | Lazy imports; tests use injected fakes; real-model use is documented as unbenchmarked |
