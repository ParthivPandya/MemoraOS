# Retrieval (v0.2)

## Pipeline

`route → strategy (exact | temporal | fusion | graph | hybrid | …) → fallbacks → support check → evidence`. The `hybrid` stage fuses the configured retrievers, optionally over query variants, then optionally reranks.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `fusion_strategy` | `rrf` | `rrf` (equal), `weighted_rrf` (uses `fusion_weights`), `linear` (min-max scores) |
| `fusion_retrievers` | `[bm25, vector]` | any of `bm25`, `vector`, `entity`, `exact` |
| `query_expansion` | `false` | add deterministic variants (original kept first at full weight) |
| `query_rewrite_llm` | `false` | add LLM paraphrases that keep every name and number of the original |
| `predicate_hints` | `true` | "how much … make" → salary, for fact lookup only |
| `rerank` / `rerank_top_n` | `off` / 20 | reorder the fused head; any reranker failure keeps the fused order |
| `evidence_fusion` | `true` | typed multi-hop path search (below) |
| `answer_max_sentences` | `3` | passage answers may quote up to this many sentences (extra sentences must share one memory for chain questions) |
| `head_guard_coverage` | `0.75` | the attribute-word guard is waived when evidence covers at least this fraction of the question's terms (`1.01` restores the v0.1 behaviour) |
| `min_anchor_coverage` | `0.5` | when an answer is composed of extra sentences, the best single sentence must cover at least this fraction of the question's terms by itself (precision/recall knob) |

Entity and exact retrievers read the live index only; historical (`as_of`) queries use BM25 + vector so nothing from the present leaks into the past.

## Evidence fusion (`strategy="fusion"`)

For a question like *"Which Azure region is used by the project Alice manages?"* the planner finds the **answer type** (region → `hosted_in`), an **anchor** (Alice) and the **first relation** (manages → `leads`, outgoing). The searcher enumerates simple paths over facts valid at the requested time, with hard bounds (`evidence_max_hops`, `evidence_max_paths`, `evidence_max_expansions`). Each step must be a stored fact with a source memory, followed in the right direction, without revisiting an entity. One terminal value → answer; several, or a contradicted step → `conflict`; none → `insufficient_evidence`. Confidence is the minimum over the steps, and the path is in the evidence and the plan notes. If the question names no chain, fusion is not applicable and ordinary strategies run. Details: [ADR-0006](ADR/0006-evidence-fusion-typed-path-search.md).

An **answer-type guard** also applies to plain fact and passage answers: a fact or passage that cannot be of the requested kind never answers (it fixed a confidently wrong "Project Atlas" for a region question).

## Real-document findings (what the synthetic suite had hidden)

`python -m benchmarks.real_docs` asks questions about MemoraOS's own documentation (real text, not generated; see [REAL_DOCS.md](../benchmarks/reports/REAL_DOCS.md)). Its first run, with the v0.2 code as originally written, scored far below plain hybrid RAG, and diagnosing the failures with `explain()` found concrete defects. A held-out question set was frozen before any fix, so the fixes could be checked on questions they were not shaped by.

| Defect found on real text | Fix |
|---|---|
| The negation guard dropped a whole document section whenever any sentence in it contained "not" or "never" (a regression introduced in v0.2). | Suppression is now per sentence: only the sentence that states the negation, or whose fact a later negation retired, is withheld. |
| A passage answer could quote only one sentence, although answers often span two. | `answer_max_sentences` (default 3): further sentences are added only while they cover a question term not yet covered. For chain questions, extra sentences must come from the same memory, so an answer is never stitched together from unrelated memories. |
| The "attribute word" guard demanded the question's last content word in the evidence ("disk", "intermittently", "bump"), which natural questions use loosely. | `head_guard_coverage` (default 0.75): the guard is waived only when the evidence already covers at least that fraction of the question's terms. |
| A bare "before"/"after"/"since" routed prose questions to the temporal and episodic strategies, which returned an anchor sentence as the "answer". | These words are now weak cues unless a time reference is parsed, a fact slot matches, or the question has an episodic cue. |
| Two capitalised names alone triggered the co-mention graph strategy. | The multi-hop category now needs a relation cue; chains are handled by evidence fusion. |
| Chunk overlap was a character slice, so every chunk after the first began mid-sentence (inside a table row); the fragment then surfaced in answers. | Overlap is now a whole preceding unit (a sentence or line), and only if it fits. |
| Found by `benchmarks/real_temporal.py`: a question about a version the stored facts never mention was answered from the unversioned subject's facts. | A subject qualified by a version that none of its stored values mention no longer matches (`_unseen_qualifier`). |
| Found by the same run: a passage was returned for a question naming a version it never contains, because the other words matched. | A passage answer is refused when the question names a version or number that the answer text lacks (`_unmentioned_version`). |
| With multi-sentence answers, coverage could add up across sentences that each supported almost nothing: an unrelated roadmap line was returned as an "answer" it did not support. | Extra sentences may extend an answer but never create its support: the best single sentence must meet `min_anchor_coverage` (default 0.5) on its own. Lowering it answers more real questions and refuses fewer unanswerable ones; `REAL_DOCS.md` publishes that trade-off as `memoraos[anchor=x]` rows. |

The two answer-composition settings were adopted under the same rule as every other default: the ablation (`ABLATION_V02.md`) shows no scenario regresses on the synthetic suite. A first version of the multi-sentence change did regress the evidence-fusion unit tests (it stitched sentences from different memories into a confident but unsupported answer); those tests caught it and the same-memory rule above is the result.

Limits: the question set is small and project-authored, the corpus is the project's own prose, and the held-out set is only held out from *these* fixes, not from the authors. Answers are **extractive passages**, not written prose: when an answer needs a neighbouring sentence it may be stitched from adjacent memories (restricting extra sentences to one memory was measured and lost a large share of correct answers). Pass `synthesize=True` with a chat provider for fluent answers; that path is not benchmarked. The scoring is mechanical (the answer contains the gold string), which can reward an answer that contains the gold string incidentally; MRR and evidence-hit are reported alongside for that reason.

## Ablation (measured, not assumed)

`python -m benchmarks.ablations` → [ABLATION_V02.md](../benchmarks/reports/ABLATION_V02.md). Rule: a component becomes a default only if it lowers no scenario. Results on the 19 synthetic scenarios (3 seeds):

- Evidence fusion on: evidence-fusion scenario 100% vs 50% off. Predicate hints on: `paraphrase_robustness` 100% vs 88.6% off. Multi-sentence answers (`answer_max_sentences=3`): `paraphrase_robustness` 100% vs 88.6% at 1. The relaxed attribute guard (`head_guard_coverage`) changes nothing on the synthetic suite; it is justified by the real-document benchmark instead. All four ship **on**.
- Entity retriever: slightly lowers `temporal_reasoning` when hybrid is forced (45.9% → 44.4%), no gain in the full pipeline. Exact retriever, expansion, lexical reranking and linear fusion: no change in the full pipeline. All ship **off**.
- Linear fusion improves several scenarios only when the fact engine is bypassed (forced hybrid); not in the full pipeline.

These datasets are lexical and project-authored. A neural embedder, cross-encoder or real LLM rewrite may behave differently; that is **not measured**.
