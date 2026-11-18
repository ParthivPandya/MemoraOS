# Benchmark Methodology

The Memory Benchmark Lab is part of the product. It is deterministic, executable with one command, and reports only what it measured.

```bash
python -m benchmarks.run                       # 3 seeds, full size (~2 min on a laptop) -> benchmarks/reports/
python -m benchmarks.run --quick --seed 7      # smoke run
python -m benchmarks.run --scenarios temporal_reasoning contradiction_resolution
memoraos bench                                 # same thing through the CLI
```

Outputs: `benchmarks/reports/benchmark_results.json` (all data, environment, config, dataset hashes, a **deterministic digest** of every non-timing number) and `REPORT.md` (rendered from the JSON by `benchmarks/report.py`; nothing is hand-edited). The dashboard's Benchmarks page renders the JSON.

## Systems

| Name | What it is |
|---|---|
| `bm25`, `vector`, `hybrid_rag` | Classical RAG built from the same tokenizer, embedder, chunker and extractive reader as MemoraOS: BM25 only / cosine only / BM25+vector with RRF. Always answer. |
| `hybrid_rag_top1` | `hybrid_rag` whose reader returns one sentence instead of up to three |
| `hybrid_rag_gated` | `hybrid_rag` plus the same abstention rule MemoraOS uses (≥ 50% question-term coverage), so differences are not only "MemoraOS refuses sometimes" |
| `memoraos_hybrid_only` | MemoraOS forced to hybrid retrieval — router and fact engine disabled (ablation) |
| `memoraos` | Full pipeline |
| Mem0, Graphiti, Hindsight, Memorilla | **Not executed.** `benchmarks/systems.py::EXTERNAL` probes whether the package is installed and records why a run is impossible (LLM/graph DB/GPU required, no adapter yet). No numbers are reported or estimated. |

## Scenarios (14 required + 1 robustness)

Generated from a seed with `random.Random` (no network, no files). Required scenarios: single-fact recall, multi-document recall, multi-hop reasoning, temporal reasoning, historical reconstruction, contradiction resolution, user personalization, long conversation, long document retrieval, memory update/correction, memory consolidation, evidence attribution, retrieval after restart, degradation after repeated updates. Added: unsupported answers and **paraphrase robustness** (designed to expose weaknesses).

Details that matter:

- *Temporal*: histories are ingested out of chronological order; questions ask current / at-year / previous.
- *Historical*: `as_of` questions at each point, plus a date before anything was known (the correct behaviour is to abstain).
- *Contradiction*: Angular 16 → 19 updates (must resolve to the latest and **not** be flagged) and two documents that disagree about a database (must be **flagged**).
- *Persistence*: disk-backed systems close and reopen; in-memory baselines rebuild their index from the raw documents.
- *Consolidation*: MemoraOS consolidates, then every original memory is read back byte-for-byte.
- *Degradation*: services whose status is overwritten 1…40 times; accuracy measured after 1, 5, 10, 20, 40 updates.

## Scoring (all mechanical, no LLM judge)

An answerable question is correct iff the system did not abstain, the answer contains **every** gold string and **no** stale/wrong string. Unanswerable questions are correct iff the system abstained. Conflict questions are correct iff the system flagged a conflict; update questions iff the latest value is returned and no conflict is flagged.

Metrics: accuracy (exact-match containment) with 95% bootstrap CI (1000 resamples, fixed seed), Recall@5, Precision@5, MRR, nDCG@5 over *source-event ids* of returned evidence, evidence coverage (a relevant source is among returned evidence), unsupported-answer rate, false-abstain rate, contradiction-detection accuracy, citation exactness (top evidence is the right note and its excerpt contains the answer), temporal accuracy by case, context tokens (≈ 4 chars/token estimate of returned evidence), retrieval latency (p50/p95), update cost (ms/event), storage ÷ raw text, restart time.

## Reproducibility

Fixed seeds, injectable clock and id factory, no randomness at query time. The report states command, seeds, scale, dataset SHA-256 per seed, hardware, Python/NumPy/SQLite versions, embedder, and that no LLM is used. `tests/regression/test_regression.py` checks that the dataset hash and result digest are stable. Timings vary by machine and are excluded from the digest.

## Real-document benchmark

The scenarios above are synthetic. `python -m benchmarks.real_docs` complements them with real text: it ingests MemoraOS's own documentation, split into heading sections exactly as written, and asks hand-written questions about it. It uses the same systems and the same mechanical judge. Integrity is enforced in code: each gold answer must occur verbatim in the corpus and each unanswerable question's key term must be absent, otherwise the run aborts. The question set has a dev part (used to find defects) and a held-out part (written before the fixes and never used for tuning). Output: `benchmarks/reports/REAL_DOCS.md` and `real_docs_results.json` (including every answer MemoraOS gave and the section it cited). `real_docs_before_fixes.json` keeps the first run for comparison. Limits: small corpus, project-authored questions, README and `docs/EVIDENCE.md` excluded so an answer cannot come from the page that reports the result.

## Real temporal benchmark

`python -m benchmarks.real_temporal` tests what the prose benchmark cannot: change over time. The data is the dated CPython release history copied from three PEPs (`data/python_releases.json`, with source URLs). Every record becomes one templated sentence that all systems receive identically, and the questions (current value, previous value, value on a date in the middle of each validity interval, plus unanswerable ones) have gold answers computed from the real dates. Output: `benchmarks/reports/REAL_TEMPORAL.md` and `real_temporal_results.json`. Limits: one fact family, few questions, templated sentences, project-authored unanswerable questions.

## Results snapshot

From `benchmarks/reports/REPORT.md` (3 seeds, ≈ 850 questions pooled; Windows 11, 8 logical CPUs, 7.7 GB RAM, Python 3.14.3). Re-run the command to reproduce; do not rely on this copy.

| System | Macro accuracy | Pooled accuracy, 19 scenarios [95% CI] |
|---|---|---|
| bm25 | 58.6% | 60.3% [57.1, 63.4] |
| vector | 60.7% | 64.7% [61.7, 67.7] |
| hybrid_rag | 56.3% | 57.9% [54.8, 61.0] |
| hybrid_rag_gated | 57.6% | 59.2% [56.0, 62.1] |
| memoraos_hybrid_only | 73.7% | 76.9% [74.2, 79.6] |
| **memoraos** | **100.0%** | **100.0% [100.0, 100.0]** |

On the 16 v0.1 scenarios alone (unchanged definitions) MemoraOS is 100% (was 97.2% in v0.1); the 3 v0.2 scenarios are 100% for MemoraOS and 22–26% for the RAG baselines. Those 3 were written for v0.2's features, so treat them as feature checks. **A perfect score on datasets written by the same project means this synthetic suite no longer discriminates for MemoraOS**; it still guards against regressions, but the real-document benchmark below is the harder and more informative test.

Where the gap comes from (all in the report): multi-document aggregation, multi-hop chains, temporal and historical questions, contradiction handling, update/correction and degradation — capabilities RAG baselines do not have — plus abstention (0% vs. 37.5–100% unsupported-answer rate). The ablation row shows these gains come from routing + the fact/truth engine, not from the retrieval primitives: forcing plain hybrid retrieval leaves 76.9%. (It was 62.8% before the passage fallback learned to prefer the later of two near-identical statements, a heuristic that helps wherever no fact was extracted; see the CHANGELOG.)

Where MemoraOS lost earlier: `paraphrase_robustness` was 77.1% in v0.1 against 100% for plain RAG. It is 100% now, from three changes (predicate hints, multi-sentence answers, a relaxed attribute guard). The synthetic phrasings are templated by the same authors, so this shows the mechanisms work on those templates, not that paraphrase robustness is solved; real prose is measured in the real-document benchmark, where MemoraOS is **not** ahead of a gated RAG baseline.

Other costs, from the committed report (timings are machine- and run-dependent; two runs on this machine differed by about 2.5×, so trust only the ratios): ~351× storage vs. raw text on very short texts (indexes, vectors, facts, version history, audit log; 59× for baselines); update cost ≈ 5× the baseline's per event; query latency p50 ≈ 2.5–3× the baseline's; while returning ≈ 29 context tokens per question vs. ≈ 70–79 (answers are shorter because they are facts, not three sentences).

## Limitations — read before quoting

1. Datasets are **synthetic and authored by this project** around capabilities MemoraOS implements, using templated English its extractor is designed for. The result demonstrates mechanisms, not real-world superiority.
2. The embedder is lexical; semantic recall with neural embedders is unmeasured.
3. Baselines are simple classical pipelines, not production systems; strong RAG with an LLM reader/reranker would score higher on several scenarios.
4. No external system was run.
5. Single machine; latency numbers are indicative.

## Adding a scenario or system

Scenario: add a builder to `benchmarks/datasets.py::BUILDERS` returning `Scenario(events, questions)` and add a judging rule only if the generic rules do not fit. System: subclass `System` in `benchmarks/systems.py` (`add`, `correct`, `ask`, optional `restart`) and register it in `available_systems`. An external-system adapter must really execute the system and may not hard-code or copy published numbers.

Roadmap: LoCoMo and LongMemEval adapters (license permitting) so results can be compared against the published literature with a fixed judge.
