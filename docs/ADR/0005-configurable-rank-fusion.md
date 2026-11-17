# ADR-0005: Configurable weighted RRF with entity and exact-value retrievers

**Status:** Accepted · 2026-11-17

**Context.** v0.1 fuses BM25 and vector with RRF at a fixed `k`. Scores from different retrievers are not comparable, so rank-based fusion is right, but weights and retriever sets must be configurable and entity/identifier retrieval is missing.

**Decision.**
- `Settings` gains `fusion_strategy` (`rrf` | `weighted_rrf`), `rrf_k` (existing) and `fusion_weights` (per retriever, default 1.0). Fused values are rank scores, documented as **not probabilities**.
- New retrievers behind one interface: `entity` (mentions and aliases) and `exact` (identifiers, quoted strings, numbers/values via `value_key`).
- Query expansion produces additional ranked lists (expanded terms) weighted below the original (0.5 by default). The original query is always searched and logged; expansion cannot remove or replace it.
- Whether entity/exact lists join the default hybrid is decided by benchmark: any scenario regression keeps them opt-in.

**Consequences.** Retrieval behavior is tunable and explainable per retriever (`explain()` shows ranks per list).
