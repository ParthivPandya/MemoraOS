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

## Results snapshot

From `benchmarks/reports/REPORT.md` (3 seeds, ≈ 850 questions pooled; Windows 11, 8 logical CPUs, 7.7 GB RAM, Python 3.14.3). Re-run the command to reproduce; do not rely on this copy.

| System | Macro accuracy | Pooled accuracy [95% CI] |
|---|---|---|
| bm25 | 65.5% | 65.2% [62.2, 68.4] |
| vector | 67.4% | 69.9% [66.8, 72.9] |
| hybrid_rag | 63.1% | 62.8% [59.7, 66.0] |
| hybrid_rag_gated | 64.7% | 64.2% [60.9, 67.3] |
| memoraos_hybrid_only | 62.9% | 58.0% [54.6, 61.4] |
| **memoraos** | **98.6%** | **97.2% [96.0, 98.2]** |

Where the gap comes from (all in the report): multi-document aggregation, multi-hop chains, temporal and historical questions, contradiction handling, update/correction and degradation — capabilities RAG baselines do not have — plus abstention (0% vs. 37.5–100% unsupported-answer rate). The ablation row shows these gains come from routing + the fact/truth engine, not from the retrieval primitives.

Where MemoraOS **loses**: `paraphrase_robustness` — MemoraOS 77.1% vs. 100% for plain RAG (88.6% for the gated RAG baseline). Failures are phrasings the rule-based extractor does not cover ("You can reach P in C these days", "how much does P make?"), where the strict support check abstains. This is a real weakness, tracked in the roadmap.

Other costs: ~351× storage vs. raw text on very short texts (indexes, vectors, facts, version history, audit log; 59× for baselines), ~13.7 ms update cost per event vs. ~2.7 ms, query latency p50 ≈ 6.5 ms vs. ≈ 1.5–2.2 ms, while returning ≈ 29 context tokens per question vs. ≈ 70–79 (answers are shorter because they are facts, not three sentences).

## Limitations — read before quoting

1. Datasets are **synthetic and authored by this project** around capabilities MemoraOS implements, using templated English its extractor is designed for. The result demonstrates mechanisms, not real-world superiority.
2. The embedder is lexical; semantic recall with neural embedders is unmeasured.
3. Baselines are simple classical pipelines, not production systems; strong RAG with an LLM reader/reranker would score higher on several scenarios.
4. No external system was run.
5. Single machine; latency numbers are indicative.

## Adding a scenario or system

Scenario: add a builder to `benchmarks/datasets.py::BUILDERS` returning `Scenario(events, questions)` and add a judging rule only if the generic rules do not fit. System: subclass `System` in `benchmarks/systems.py` (`add`, `correct`, `ask`, optional `restart`) and register it in `available_systems`. An external-system adapter must really execute the system and may not hard-code or copy published numbers.

Roadmap: LoCoMo and LongMemEval adapters (license permitting) so results can be compared against the published literature with a fixed judge.
