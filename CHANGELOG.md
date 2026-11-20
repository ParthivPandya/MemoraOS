# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased] - MemoraOS Next (work in progress on `feature/memoraos-next`)

Status of each item: see `docs/NEXT_IMPLEMENTATION_STATUS.md`. Nothing here changes a default; every new behaviour is opt-in.

### Added
- **Encryption at rest** (opt-in): AES-256-GCM with a scrypt-derived key, `Settings.encryption_passphrase` or `MEMORAOS_ENCRYPTION_KEY`, `memoraos encrypt` / `memoraos decrypt`, encrypted backups, no plaintext `sources/` copy. Extra: `memoraos[encryption]`. Every commit rewrites the file, so writes cost O(database size). See `docs/SECURITY.md`.
- **Docker**: `Dockerfile`, `.dockerignore`, `docker-compose.yml` (non-root, `/data` volume, health check, loopback port). See `docs/DOCKER.md`.
- **Public benchmarks, retrieval only** (`python -m benchmarks.public locomo|longmemeval`): LoCoMo (1,532 questions) and a 60-question LongMemEval-S sample against BM25, vector and hybrid baselines, with Wilson intervals and paired counts. Plain BM25 is at least as good as MemoraOS here. See `docs/PUBLIC_BENCHMARKS.md`.
- **Opt-in IVF vector index** (`Settings.vector_index="ivf"`) and `python -m benchmarks.scaling`. Measured recall 0.52-0.93, so exact search stays the default. See `docs/SCALING.md`.
- `memoraos ci run --set KEY=VALUE` (repeatable) and `--embedder`.
- `docs/COMPETITIVE_INTELLIGENCE.md`: sourced comparison of other memory systems and benchmarks, with unverified items marked.
- **Memory CI** (`memoraos ci run|compare`, `memoraos.contracts`): memory contracts in JSON (or YAML with PyYAML) with expected answers, expected refusals, temporal and evidence requirements, tenant-isolation checks and token budgets, plus a regression report against a previous run (broken expectations, abstention that got worse, new unsupported answers, status changes, token/latency deltas). Exit code 1 on a failed assertion or regression. Guide: `docs/MEMORY_CI.md`.
- **Answerability policies** (`Settings.answerability`: `strict` (default, unchanged), `balanced`, `high_recall`, `extractive_only`): optional section-level and, with a neural embedder, semantic support for answers. Measured, and not enabled by default because the independent validation set did not confirm the dev-set gain. Details and every number: `docs/NEXT_ANSWERABILITY.md`.
- **Failure taxonomy** for the real-document benchmark (`python -m benchmarks.failures`): every wrong answer gets exactly one cause read from the engine's own trace.
- **Answerability evaluation** (`python -m benchmarks.answerability`): Wilson intervals, answerable recall, false-abstention and unsupported-answer rates, correct abstention, Brier score and ECE, a separate validation set (V2), and optional neural-embedder runs (`--embedder`).
- `benchmarks/stats.py` (Wilson interval, Brier, ECE).

### Fixed
- The documents-only passage fallback returned the **older** of two near-identical statements ("The customer plan is Basic" / "...Premium" with no extracted facts). It now quotes the later one when both cover exactly the same question terms and are otherwise near-identical, flags the earlier as `older_variant`, and leaves questions that name a time to the temporal strategies. Side effect, disclosed: the forced-hybrid ablation rises (synthetic 62.8% to 76.9%, real temporal 33.3% to 38.1%); the full engine's results are unchanged and the synthetic digest is now `c35859a13f53`.
- `docs/SECURITY.md`, the roadmap and the status docs no longer say encryption at rest is missing.
- `plan` and `tier` are single-valued attributes, so "the current plan" no longer returns the old and the new plan together (found while writing a Memory CI contract).

## [0.3.0] - 2026-11-20

### Added
- **Verifiable citations**: every `Evidence` carries `span_start`, `span_end` and `quote_sha256`. `MemoryOS.verify_citations` and `POST /v1/verify-citations` re-check each quote against the stored memory and the retained source (statuses: verified, unlocated, quote_changed, source_mismatch, memory_missing). Proves a quote exists unchanged; does not prove it supports the answer and does not change accuracy. See `docs/CITATIONS.md`; `python -m benchmarks.citations`.

## [0.2.1] - 2026-11-20

### Fixed
- **Verb forms with a silent "e" now share a stem** (`rotate`/`rotates`/`rotating`/`rotated`, `release`/`releases`). Found by installing 0.2.0 from PyPI: storing "The deploy key rotates every 90 days" and asking "how often does the deploy key rotate" was refused. It is answered with evidence now.
- Measured effect on the real-document benchmark (regenerated): two answerable questions are now correct and one is wrong (net +1), but two unanswerable questions are now wrongly answered because "require" matches "required"; overall 59.4% for MemoraOS against 64.1% for gated RAG, within noise. Public LoCoMo/LongMemEval retrieval numbers were re-run and the docs updated; the MemoraOS retriever's paired lead over hybrid RAG on LoCoMo is 35 vs 13 questions (it was 51 vs 8).
- Databases created with 0.2.0 store hashing-embedding vectors built with the old stems. Their effect after upgrading has not been measured; re-ingesting rebuilds them.

### Added
- **Docker smoke test in CI** (`scripts/docker_smoke.sh`, job `docker`): builds the image, checks health, 401 without a key, remember and recall through the API, persistence across restart, and an encrypted database file.
## [0.2.0] - 2026-11-19

Scope: Phase Zero audit, semantic extraction, embeddings and retrieval, and evidence fusion. The specification supplied for this release was truncated after Part 8.1 step 7, so anything after that point is **not** implemented. See `docs/V02_REPOSITORY_AUDIT.md`, `docs/V02_IMPLEMENTATION_PLAN.md` and `docs/ADR/`.

### Added
- **Schema migration 2** (additive; tested against a real v0.1 database in `tests/fixtures/v01.db`): fact polarity, extraction method/version, source span and normalized value columns; embedding provider/version/status metadata; `embedding_models` and `extraction_attempts` tables. An automatic `.bak-v1` copy is made before an existing database is upgraded.
- **Extraction**: negation (`does not`, `no longer`), `Correction:` prefixes, conjunction splitting into separate facts with their own source spans, inverted phrasing, `makes <money>`, owner-less `the budget is …` facts (confidence 0.5). Negated facts are stored but never answer a positive question, and retire an earlier affirmation.
- **Value normalization**: `32 LPA`, `32 lakhs annually` and `₹32 lakh per annum` share one canonical key, and monthly pay is annualised (`₹2.5 lakh per month` = `30 LPA`); a different amount, currency or period never merges.
- **Optional LLM extraction** (`extraction_mode = rules | llm | hybrid`, default `rules`): proposals are span-verified, grounded, injection-filtered and capped; failures are logged to `extraction_attempts` and fall back to rules. `MemoryOS.rebuild_facts()` re-derives facts from preserved originals.
- **Embedding provider v2** (`BaseEmbeddingProvider`, `adapt_embedder` for v0.1 providers, health checks), dimension-mismatch guard, `reembed()`, `rebuild_index()`, `embedding_info()`, optional lazy `SentenceTransformerEmbedder`.
- **Retrieval**: configurable fusion (`rrf`, `weighted_rrf`, `linear`), entity and exact-identifier/value retrievers, query expansion (original always kept), validated optional LLM paraphrase, reranker stage with `CrossEncoderReranker` and `HttpReranker`; deterministic fallback on any failure. All are off by default except where noted.
- **Evidence fusion**: typed multi-hop path search (`strategy="fusion"`) with per-step validation (valid at time, direction, no cycles, provenance), bounded search, conflict/ambiguity reporting and a path trace.
- Router: `fusion` strategy; answer-type guard so a fact of the wrong kind cannot answer ("Which region …?" is no longer answered with "Project Atlas").
- Predicate hints ("how much … make" → salary).
- Benchmarks: 3 new scenarios, v0.1-suite vs v0.2 headline split, `python -m benchmarks.ablations`.

### Fixed
- Found by the real-document benchmark (`benchmarks/real_docs.py`): negation suppression is per sentence, not per memory; passage answers can use up to 3 sentences (`answer_max_sentences`) but extra sentences cannot create support (`min_anchor_coverage`); the attribute-word guard is waived at 75% term coverage (`head_guard_coverage`); chunk overlap is a whole unit instead of a mid-sentence fragment; bare "before/after/since" no longer routes prose questions to temporal/episodic; entity names alone no longer trigger the co-mention graph. Found by `benchmarks/real_temporal.py` (real PEP release dates): a subject qualified by a version that no stored value mentions no longer matches the unqualified subject's facts, and a passage that lacks a version named in the question no longer answers it. Details and measurements: `docs/RETRIEVAL.md`.
- All examples and the dashboard seed now use real data only (MemoraOS's own docs; `data/python_releases.json`, copied from PEP 693/719/745). Tests and the synthetic benchmark generators still use controlled inputs by necessity; the benchmark is labelled synthetic wherever it is quoted.
- Windows CI flake: system time is now strictly monotonic and timeline ordering is stable (ADR-0007).
- Weekday/imperative words no longer become entities; named attributes win over generic verb predicates.

### Changed
- `Settings` gains extraction, fusion, expansion, rerank and evidence-fusion options; every default preserves v0.1 behaviour except evidence fusion and predicate hints, which are on.
- `MemoryOS.facts()` includes negated facts; `load_facts()` excludes them by default.
- `schema_version` is now 2.

### Benchmark (synthetic, project-authored; see README and docs for caveats)
- v0.1 suite: MemoraOS 97.2% → 100%; v0.2 scenarios: 100% (written for these features). A perfect score on self-authored synthetic data means that suite no longer discriminates for MemoraOS; the real-document benchmark (`benchmarks/reports/REAL_DOCS.md`) is the harder test and reports parity-or-worse against gated RAG on answerable questions, with better refusal of unanswerable ones.
- Entity/exact retrievers, expansion, lexical reranking and linear fusion did not improve the full pipeline, so they stay off by default.

### Not verified
- LLM extraction and neural embedders/rerankers were tested with scripted fakes only; real-model quality is unmeasured.

## [0.1.0] - 2026-11-17

### Added
- SQLite-first memory engine: versioned migrations, WAL, FTS5 BM25, cached embeddings, online backup.
- Ingestion: text, conversations, structured JSON, documents; chunking; secret redaction; rule-based fact/entity/date extraction; duplicate detection.
- Retrieval: BM25, vector, RRF hybrid, graph (multi-hop), episodic, procedural, temporal, multistage; optional latent strategy (experimental).
- Adaptive router with cost-aware selection, fallbacks, optional model classifier, and accuracy-guarded feedback learning (off by default).
- Truth engine: bitemporal fact timelines, contradiction/version-change analysis, source reliability, evidence-supported answers, abstention.
- Time travel: version history, as-of recall, snapshots, change log, hash-chained event log.
- Consolidation: near-duplicate links, conservative alias merges, derived summaries, importance, incremental/dry-run/scheduled modes, rollback.
- Multi-tenant isolation with user/session/agent/project/org scopes; export; hard delete.
- REST API (API-key auth, roles, audit log), Python client, TypeScript SDK, MCP stdio server, CLI.
- Next.js dashboard backed by live API data.
- Memory Benchmark Lab with 15 scenarios, baselines, ablation, bootstrap CIs, deterministic digest.
- Provider abstraction: Ollama and OpenAI-compatible adapters with retries, timeouts, fallbacks, usage tracking.

### Known limitations
See README "Limitations" and docs/IMPLEMENTATION_STATUS.md.
