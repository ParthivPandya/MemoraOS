# Adaptive Memory Routing Engine (AMRE)

The router decides *which retrieval strategy answers a question*. It is deterministic, needs no LLM, and every decision is observable (`RecallResult.plan`, `explain(recall_id)`, dashboard "Retrieval strategies").

## Pipeline

1. **Features** (`routing.router.analyze_query`): exact-fact cue, temporal cue (+ parsed time reference: "in 2025", "last three years", "before March 2025"), history/previous cues, multi-hop cue, personalization (first person), procedural cue, episodic cue, summary cue, code-like tokens (`E4021`, `snake_case`, quoted literals), capitalised entity count, content terms (time filler removed), attribute head word.
2. **Hints from the store** (`RouterHints`): does a stored fact slot match the question's subject+attribute? how many graph entities does it name? do procedural memories exist? is latent memory enabled?
3. **Category scores** (0–1) for `exact_fact`, `temporal`, `multi_hop`, `procedural`, `episodic`, `summarization`, `semantic` (default). Weights are explicit in `category_scores`.
4. **Strategy selection**: every strategy gets a score from the category evidence; among strategies within `cost_tolerance` (default 0.1) of the best, the **cheapest** wins (`STRATEGY_COST`: exact 1 … multistage 10). The category's canonical strategy wins ties.
5. **Fallbacks**: category-specific, always ending in `hybrid`, `vector`. Low route confidence (< 0.25) promotes `hybrid` and optionally consults a model classifier (`ChatProvider`; output validated against the label set; failures ignored).
6. **Execution**: the Recaller tries stages in order and stops at the first **supported** outcome (see MEMORY_DESIGN). `strategies_tried` and `fallback_used` are returned.

## Categories → strategies

| Question | Category | Primary | Fallbacks |
|---|---|---|---|
| "What is my exact current salary?" | exact_fact | `exact` (slot lookup + timeline) | hybrid |
| "What was Parth's salary in 2025?" | temporal | `temporal` | episodic, hybrid |
| "How is Alice related to Azure Functions?" | multi_hop | `graph` | hybrid |
| "How do I deploy Project Atlas?" | procedural | `procedural` | hybrid |
| "What happened before the Atlas migration failed?" | episodic | `episodic` (anchor event, follow shared entities in time order) | temporal, hybrid |
| "Summarize everything about AI memory" | summarization | `multistage` (BM25 + vector + graph + latent, fused; derived summaries preferred) | hybrid |
| "Find error E4021" | semantic | `bm25` | hybrid, vector |

These are asserted in `tests/integration/test_scenarios.py::test_i_*`.

## Adaptive strategy learning

Every recall is logged (strategy, category, latency, tokens, status). `POST /v1/feedback` / `MemoryOS.feedback(recall_id, correct=…)` attaches ground truth. `strategy_report()` aggregates accuracy per (category, strategy).

**Learning is off by default** (`Settings.adaptive_learning=False`). When enabled, a learned override replaces the default strategy only if **all** hold (`routing/learning.py`):

- both strategies have ≥ `learning_min_samples` (20) labelled outcomes in that category;
- the challenger's Wilson 95% **lower** bound ≥ the default's observed accuracy;
- the challenger's accuracy is not below the default's.

Latency and tokens only break ties between statistically-as-accurate strategies. A challenger can never win by being cheaper while less accurate, so self-optimisation cannot silently reduce accuracy. No reinforcement learning is used: there is no reliable reward signal at this scale; a contextual bandit remains future work (ROADMAP) and would need the same guard.

## Limits

Keyword heuristics are English-only and miss unusual phrasing; low-confidence cases fall back to hybrid. Routing quality is evaluated indirectly through end-to-end accuracy in the benchmark, not as a classification benchmark.
