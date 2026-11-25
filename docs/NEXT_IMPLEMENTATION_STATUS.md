# MemoraOS Next: implementation status

Statuses (exactly one per feature): COMPLETED_AND_TESTED, IMPLEMENTED_NOT_FULLY_VERIFIED, PARTIALLY_IMPLEMENTED, DEFERRED, BLOCKED. Work is on branch `feature/memoraos-next`; nothing is committed, released or published, and no repository metadata was changed.

## Features

| Feature | Status | Verified by | Notes |
|---|---|---|---|
| Phase 0 audit, gap analysis, plan | COMPLETED_AND_TESTED | Commands in [NEXT_REPOSITORY_AUDIT.md](NEXT_REPOSITORY_AUDIT.md) | Audit statements are backed by commands run in this session. |
| Failure taxonomy (`benchmarks/failures.py`) | PARTIALLY_IMPLEMENTED | `python -m benchmarks.failures` | 5 of the spec's 14 causes (retrieval miss, over-strict abstention, answer generation, evidence fusion, false acceptance). The others need extraction, entity, temporal and citation datasets. No unit test of its own; it is exercised by the benchmark run. |
| Answerability evaluation (`benchmarks/answerability.py`, `benchmarks/stats.py`) | COMPLETED_AND_TESTED | `python -m benchmarks.answerability`; report in [NEXT_ANSWERABILITY.md](NEXT_ANSWERABILITY.md) | Wilson intervals, recall, unsupported rate, correct abstention, Brier, ECE, validation set V2. `stats.py` is covered by `tests/unit/test_benchmark_stats.py`. |
| Answerability policies (`strict`, `balanced`, `high_recall`, `extractive_only`) | IMPLEMENTED_NOT_FULLY_VERIFIED | `tests/unit/test_answerability_policies.py` (6 tests, controlled inputs) and the benchmark | Mechanism tested; **benefit not demonstrated**: the independent set did not confirm the dev gain. Default remains `strict`. Semantic path tested with a stub embedder and measured with one real model only. |
| Real neural embedder benchmark (MiniLM-L6-v2) | PARTIALLY_IMPLEMENTED | `answerability_neural.json` | One model, one corpus. Other models: not run. |
| Memory CI (`memoraos ci`, `memoraos.contracts`) | COMPLETED_AND_TESTED | `tests/unit/test_memory_ci.py` (13 tests incl. an injected regression), real-data contract `contracts/python_releases_and_security.json` 7/7, wheel smoke test | Automatic triggers (schema, provider or skill changes), CLI provider selection and a CI template are not implemented. |
| `plan` / `tier` single-valued fix | COMPLETED_AND_TESTED | `tests/unit/test_real_text_regressions.py` | |
| LLM extraction against a real model (#1) | BLOCKED | | No local LLM runtime or API key here. The span-verification, grounding, injection filtering and fallback paths are tested with scripted fakes only; quality on a real model is unmeasured. |
| ANN index (#2) | IMPLEMENTED_NOT_FULLY_VERIFIED | `tests/unit/test_ann.py` (3), `python -m benchmarks.scaling`, [SCALING.md](SCALING.md) | Opt-in numpy IVF (`vector_index="ivf"`). Measured recall@10 0.52-0.93 on real text with the hashing embedder, so it is not recommended and exact search stays the default (3.5 ms at 20k, 25 ms at 100k, 139 ms at 500k vectors). Not measured with a neural embedder. |
| LoCoMo and LongMemEval retrieval adapters (#3) | COMPLETED_AND_TESTED | `python -m benchmarks.public`, `tests/unit/test_public_bench.py` (3), [PUBLIC_BENCHMARKS.md](PUBLIC_BENCHMARKS.md) | Retrieval only, hashing embedder, LongMemEval sample of 60. Plain BM25 is at least as good as MemoraOS. No LLM-judged answer accuracy (BLOCKED: needs an LLM). |
| Encryption at rest (#4) | COMPLETED_AND_TESTED | `tests/unit/test_encryption.py` (9), CLI `encrypt`/`decrypt`, Docker smoke test | AES-256-GCM, scrypt, opt-in; every commit rewrites the encrypted file (O(database size)). Not independently audited. Key rotation not implemented. |
| Docker (#5) | COMPLETED_AND_TESTED | Image built and run on Docker Desktop: healthy, 401 without a key, remember+recall through the API, survives restart, encrypted volume; [DOCKER.md](DOCKER.md) | Other runtimes and architectures not tried. A CI job (`scripts/docker_smoke.sh`) runs the same checks from 0.2.1. |
| Documents-only fallback returned the older statement | COMPLETED_AND_TESTED | 3 tests in `tests/unit/test_real_text_regressions.py` | Recency rule for near-identical statements; skipped for timed questions. It changes the forced-hybrid ablation (synthetic 62.8% to 76.9%; real temporal 33.3% to 38.1%), not the full engine. |
| `memoraos ci run --set KEY=VALUE`, `--embedder` | COMPLETED_AND_TESTED | `tests/unit/test_memory_ci.py` | |
| Entity resolution v2, lifecycle states, memory controls | DEFERRED | | Need a schema migration; designed in the gap analysis only. Not started in this pass. |
| Experience and skill memory, Memory Change Sets | DEFERRED | | Not started. |
| Competitor execution | DEFERRED | | Every competitor stays NOT_EVALUATED. |
| Competitor and research intelligence ([COMPETITIVE_INTELLIGENCE.md](COMPETITIVE_INTELLIGENCE.md)) | IMPLEMENTED_NOT_FULLY_VERIFIED | Sources are cited per claim; unverified items are marked "not verified" | Written from primary sources by a research pass and read through for unsupported claims; not every URL was re-fetched. No superiority claim. |
| Multimodal ingestion, connectors, framework adapters, .NET client | DEFERRED | | |
| Memorilla adapter | DEFERRED | | Needs a CUDA GPU. |
| Presets | DEFERRED | | Only from measured configurations. |

## Commands

```bash
python -m pytest -q                                        # 358 tests
python -m ruff check src tests benchmarks scripts examples
python -m bandit -q -r src -ll -c pyproject.toml
python -m benchmarks.run                                   # synthetic; digest fca60a1fe780
python -m benchmarks.real_docs && python -m benchmarks.real_temporal
python -m benchmarks.failures
python -m benchmarks.answerability --tag hashing
python -m benchmarks.answerability --embedder sentence-transformers/all-MiniLM-L6-v2 --tag neural
memoraos ci run contracts/python_releases_and_security.json
```

## Migration and compatibility

No schema migration and no API change. `Settings` gained `answerability`, `memory_support_coverage`, `semantic_support`, `memory_window`, `vector_index` (default `exact`), `ann_min_vectors`, `ann_nprobe` and `encryption_passphrase`; with the defaults those change nothing. **One default-path behaviour did change:** the documents-only passage fallback now prefers the later of two near-identical statements (it used to return the first). The full engine's benchmark results are identical, but the forced-hybrid ablation moved, so the synthetic digest changed from `6a27829d09a1b0b9` to `c35859a13f53`. The TypeScript SDK and REST API are untouched. New CLI: `memoraos ci`, `memoraos encrypt`, `memoraos decrypt`.

## Known risks

- The answer-or-abstain decision still refuses about half of the answerable real-document questions (see [NEXT_ANSWERABILITY.md](NEXT_ANSWERABILITY.md)).
- The held-out set has been inspected; a fresh set must be written before the next answerability change.
- The recency rule applies only to the passage path with identical covered question terms; two conflicting statements that differ in wording more than that are still not resolved.
- Encrypted databases rewrite the whole file on every commit.
- Everything measured is on project-authored data, apart from the retrieval-only public runs.

## Suggested repository description

The GitHub description currently quotes the saturated synthetic result ("97.2% accuracy vs 65-70% for plain RAG"). A description that matches the evidence:

> Local-first memory engine for AI agents: bitemporal facts, evidence on every answer, explicit abstention, memory CI, reproducible benchmarks. No API key, no cloud. Alpha; benchmark results and limits in the README.

Command (not run): `gh repo edit ParthivPandya/MemoraOS --description "<text above>"`.

## Suggested community issues

1. Write V3 answerability questions from documents none of the earlier sets touched.
2. Run `benchmarks.answerability` and `benchmarks.public --embedder ...` with two more local embedding models and report cost.
3. LLM-judged answer accuracy on LoCoMo and LongMemEval (needs a disclosed judge and a model).
4. Measure the IVF index with a neural embedder.
5. Key rotation for encrypted databases.
6. A real-model run of the LLM extractor (issue #1).

