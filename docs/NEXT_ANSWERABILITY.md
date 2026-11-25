# Answerability: what was measured, and what was not achieved

Spec section 8: improve the recall of answerable questions without an unacceptable rise in unsupported answers. This page records the diagnosis, the opt-in policies that came out of it, and an honest verdict: **the gain measured on the design set did not reliably replicate on the independent validation set, so the default stays `strict`.**

Reproduce: `python -m benchmarks.failures`, `python -m benchmarks.answerability --tag hashing`, `python -m benchmarks.answerability --embedder sentence-transformers/all-MiniLM-L6-v2 --tag neural` (needs `pip install sentence-transformers`; the first run downloads the model). Corpus: this repository's documentation, 26 files, 134 sections, SHA-256 `430d72e3…`. Scoring is mechanical (the answer contains the gold string; unanswerable questions must be refused). Intervals are Wilson 95%.

## 1. Diagnosis (general mechanism, no per-question rules)

`benchmarks/failures.py` assigns each wrong answer exactly one cause from the engine's own retrieval trace. Full per-question list: [REAL_DOCS_FAILURES.md](../benchmarks/reports/REAL_DOCS_FAILURES.md).

| Cause | Count (of 27 wrong) | Meaning |
|---|---|---|
| OVERSTRICT_ABSTENTION | **12** | The section holding the answer was retrieved; the answer policy refused. 10 by the term-coverage check, 2 by the attribute-word guard. |
| ANSWER_GENERATION_FAILURE | 9 | Answered from the right section but the returned sentences lack the gold. |
| FALSE_ACCEPTANCE | 5 | An unanswerable question received an answer. |
| RETRIEVAL_MISS | 1 | No section containing the gold was retrieved. |

So 22 of 46 answerable questions are missed and **retrieval is not the main cause**. The question's words are spread across neighbouring sentences or paraphrase the document, while the support check wants one sentence to cover them.

## 2. What was tried, on the dev set only

| Idea | Dev result | Decision |
|---|---|---|
| "Unknown word" guard: refuse when a question word occurs nowhere in memory | Rejected before implementation: 11 of 30 answerable dev questions contain such a word (ordinary paraphrase), as do 11 of 12 unanswerable ones | Not built |
| Section-level support (a section covering at least X of the terms may support a windowed answer) | Recall 57% to 63% at X = 0.6 with the unsupported rate unchanged (25%); X = 0.5 raised it to 42%; no effect at 0.75 or above | Shipped as opt-in |
| Neural embedder alone (MiniLM-L6-v2) | Recall 57% to 60%: the support check is lexical, so embeddings do not reach it | Recorded |
| Semantic support (best-sentence cosine with a neural embedder; offline AUC of answerable vs unanswerable questions 0.90) | Recall 60% to 73% at cosine 0.55, unsupported 33% unchanged; 0.45 raised unsupported to 58% | Shipped as opt-in |

Policies (`Settings.answerability`), thresholds fixed from the dev set above and then frozen:

| Policy | Section support | Semantic support (neural embedder only) | Notes |
|---|---|---|---|
| `strict` (default) | off | off | Exactly the v0.2 behaviour |
| `balanced` | 0.6 | 0.55 | With a neural embedder only the semantic path is used |
| `high_recall` | 0.5 | 0.45 | Trades unsupported answers for recall |
| `extractive_only` | as balanced | as balanced | Never calls a chat provider even when `synthesize=True` |

An answer supported this way is a window of up to three sentences around the best sentence, cites the same section, and `explain()` states the basis ("supported at section level / semantic level").

## 3. Independent evaluation

The held-out set (16 + 6 questions) was written before the v0.2 fixes; the validation set V2 (25 answerable + 15 unanswerable, 10 whose key word is absent from the corpus and 5 whose every word occurs somewhere but whose fact does not) was written before any policy existed and was evaluated once, after thresholds were frozen. Counts are k/n.

| System | Dev answerable recall | Held-out recall | Validation recall | Validation unsupported answers |
|---|---|---|---|---|
| Hybrid RAG + abstention gate (lexical) | 26/30 | 12/16 | 18/25 | 14/15 |
| MemoraOS `strict` (lexical) | 18/30 | 6/16 | 14/25 | 6/15 |
| MemoraOS `balanced` (lexical) | 20/30 | 9/16 | 16/25 | 8/15 |
| MemoraOS `high_recall` (lexical) | 21/30 | 9/16 | 16/25 | 9/15 |
| Hybrid RAG + abstention gate (MiniLM) | 26/30 | 12/16 | 18/25 | 14/15 |
| MemoraOS `strict` (MiniLM) | 19/30 | 6/16 | 12/25 | 6/15 |
| MemoraOS `balanced` (MiniLM) | 22/30 | 9/16 | 12/25 | 6/15 |
| MemoraOS `high_recall` (MiniLM) | 21/30 | 9/16 | 13/25 | 9/15 |

Held-out and validation pooled (41 answerable, 21 unanswerable), recall and unsupported-answer rate:

| System | Answerable recall [95%] | Unsupported answers [95%] |
|---|---|---|
| Hybrid RAG + gate (lexical) | 30/41, 73% [58, 84] | 18/21, 86% [65, 95] |
| Hybrid RAG + gate (MiniLM) | 30/41, 73% [58, 84] | 18/21, 86% [65, 95] |
| MemoraOS `strict` (lexical) | 20/41, 49% [34, 64] | 7/21, 33% [17, 55] |
| MemoraOS `balanced` (lexical) | 25/41, 61% [46, 74] | 10/21, 48% [28, 68] |
| MemoraOS `high_recall` (lexical) | 25/41, 61% [46, 74] | 13/21, 62% [41, 79] |
| MemoraOS `strict` (MiniLM) | 18/41, 44% [30, 59] | 6/21, 29% [14, 50] |
| MemoraOS `balanced` (MiniLM) | 21/41, 51% [36, 66] | 6/21, 29% [14, 50] |
| MemoraOS `high_recall` (MiniLM) | 22/41, 54% [39, 68] | 11/21, 52% [32, 72] |

## 4. Verdict

- **No policy is shown to be better than `strict`.** All the MemoraOS intervals overlap, so no claim of improvement is made. On the held-out set `balanced` recovers 3 more answerable questions; on the validation set the lexical variant gains 2 questions and adds 2 unsupported answers, and the neural variant gains none (12/25 either way). The dev-set gain of 10 points for the neural `balanced` policy (19/30 to 22/30) was partly threshold fitting on 30 questions.
- **MemoraOS still answers far fewer answerable questions than gated RAG** (about 44 to 61% against about 73%), and it refuses far more unanswerable ones (about 38 to 71% against about 14%). That trade-off is the product's current position, not a defect that was removed.
- **The remaining gap is not closed by a small embedder.** A stronger embedder, a trained answerability classifier on labelled data, or an LLM support check are the untested options; each needs its own evaluation on a fresh set (V3) before any default changes.
- **Calibration is poor.** `evidence_coverage`, the stated confidence, has a Brier score of 0.29 to 0.32 and an expected calibration error of 0.24 to 0.29 on answered questions (all three splits, 64 to 86 answered depending on the policy and embedder). Treat it as an ordering signal, not a probability.
- **The held-out set is no longer pristine** (it was inspected during diagnosis) and validation was seen once. The next change needs a V3 set written first.
- The unanswerable set is small (21 pooled): a single question moves a rate by 5 points.

## 5. What this does not claim

The numbers in this page are regenerated with every change to the documentation corpus, and they do move: after the encryption documentation was added (one section, plus edits to status documents) several counts shifted by one question (for example the neural `balanced` validation recall went from 12/25 to 13/25 and the lexical gated-RAG held-out recall from 15/16 to 14/16), which is itself a reminder of how small these sets are. The conclusions did not change. They moved again for 0.6.0: adding documentation for the new features to the corpus (API reference, status page, changelog) changed several counts, and one answerable question ("What kind of storage changes does ADR-0001 allow?") went from answered to refused by the attribute-word guard, so MemoraOS's all-questions accuracy on the real-docs benchmark went from 59.4% to 57.8% and the gated RAG baseline from 65.6% to 67.2%, with no code change to retrieval or answering. That sensitivity to a few sentences of added text is the same small-sample caveat.

No statement here applies beyond this corpus of project-authored documentation and project-authored questions, to one neural model, or to LLM-based answering. Mem0, Graphiti, Hindsight and Memorilla were not run.

The design-time runs (baseline before any change, threshold sweeps, dev-only policy runs) are kept next to the final reports as `benchmarks/reports/answerability_baseline|sweep_dev|neural_sweep_dev|policies_*_dev.*`. They were produced on earlier states of the corpus (the documentation grew as this work was written), so compare numbers only within one report.
