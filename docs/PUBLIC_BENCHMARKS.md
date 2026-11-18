# Public benchmarks (retrieval only)

`python -m benchmarks.public {locomo|longmemeval}` runs MemoraOS and plain baselines on two public long-term-memory datasets. It needs no LLM, so the numbers are reproducible on a laptop.

> **What this is not.** Both datasets are designed for *answer* accuracy judged by an LLM. This adapter measures only whether the evidence-bearing text is retrieved. The numbers are **not comparable** to published QA scores and must not be quoted next to them.

## Data

The datasets are downloaded locally into `data/external/` (git-ignored) and are never redistributed.

| Dataset | Source | License |
|---|---|---|
| LoCoMo (`locomo10.json`) | github.com/snap-research/locomo | CC BY-NC 4.0 (non-commercial) |
| LongMemEval (`longmemeval_s_cleaned.json`) | huggingface.co/datasets/xiaowu0162/longmemeval-cleaned | see the dataset card |

## Setup

- **LoCoMo:** retrieval unit is one dialogue turn; all 1,532 questions of categories 1-4 that carry evidence labels are used (adversarial and unlabelled questions are skipped). Metrics: *any-hit@k* (at least one gold turn in the top k) and *all-hit@k* (every gold turn).
- **LongMemEval (S):** retrieval unit is a session, chunked to 800 characters; a hit means an answer-bearing session is among the sessions of the top-k chunks. Abstention questions are excluded. **60 questions**, stratified by question type with seed 7. This is a sample, so the intervals are wide.
- Embedder: the built-in hashing embedder. No neural embedder was used here.
- Systems: `bm25`, `vector`, `hybrid_rag` (BM25 + vector, reciprocal-rank fusion), `memoraos_retriever` (the MemoraOS hybrid retriever with its query handling) and `memoraos_recall` (the full `recall()` pipeline).
- 95% Wilson intervals; paired counts between `memoraos_retriever` and `hybrid_rag`.

## Results

LoCoMo, 1,532 questions ([full report](../benchmarks/reports/PUBLIC_LOCOMO.md)):

| system | any-hit@5 | any-hit@10 | all-hit@5 |
|---|---:|---:|---:|
| bm25 | 58.6% | 66.7% | 48.1% |
| vector | 45.0% | 53.0% | 36.7% |
| hybrid_rag | 53.3% | 61.8% | 43.3% |
| memoraos_retriever | 56.1% | 63.9% | 44.8% |
| memoraos_recall | 41.8% | 45.8% | 34.4% |

LongMemEval-S, 60 questions ([full report](../benchmarks/reports/PUBLIC_LONGMEMEVAL.md)):

| system | session hit@5 | session hit@10 |
|---|---:|---:|
| bm25 | 91.7% | 96.7% |
| vector | 85.0% | 90.0% |
| hybrid_rag | 90.0% | 95.0% |
| memoraos_retriever | 88.3% | 93.3% |
| memoraos_recall | 50.0% | 51.7% |

## Honest reading

- **MemoraOS does not beat plain BM25 on either set** with the hashing embedder. On LoCoMo, BM25 leads `memoraos_retriever` by about 2.5 points at k=5 (intervals overlap).
- On LoCoMo the MemoraOS retriever is **better than the fixed hybrid baseline**: at k=5, 51 questions are hit only by `memoraos_retriever` and 8 only by `hybrid_rag` (exact sign test p = 9e-9). On the LongMemEval sample the two are within one question.
- `memoraos_recall` scores low here by construction. `recall()` returns a short, answer-oriented evidence list trimmed to a token budget, not a ranked list of k items, so a top-k hit rate understates what it is for. Its value is verifiable answers, abstention and temporal handling, which these retrieval-only metrics do not measure.
- The hashing embedder is weak for paraphrase (see [PERFORMANCE.md](PERFORMANCE.md)); a neural embedder would raise the vector and hybrid rows. That run has not been done on these datasets.
- Not done: LLM-judged answer accuracy, abstention scoring, temporal-reasoning categories of LongMemEval scored on answers, and the full 500-question LongMemEval set.

## Reproduce

```bash
python -m benchmarks.public locomo
python -m benchmarks.public longmemeval --n 60     # about 9 minutes on 8 logical CPUs
```
