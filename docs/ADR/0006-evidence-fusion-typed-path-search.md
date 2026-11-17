# ADR-0006: Evidence fusion by typed path search with validated steps

**Status:** Accepted · 2026-11-17

**Context.** For *"Which Azure region is used by the project Alice manages?"* v0.1 answers `Project Atlas` with status `answered` (audit F2): the first matching fact is returned without checking that it answers the question. The answer needs three independent memories (`Alice manages Atlas`, `Atlas uses Azure Functions`, `Azure Functions is deployed in West Europe`).

**Decision.** A `fusion` strategy performs a bounded, typed search:
1. **Understand:** extract anchor entities (known to the graph), an **answer type** from the question head (region/location → `hosted_in`; a named attribute such as database → that predicate; who → reverse of `leads`), and optional relation cues (`manages` → `leads`, direction aware).
2. **Retrieve:** load currently valid facts and build a bounded subgraph (depth ≤ `max_graph_hops`, edge cap) around the anchors.
3. **Search:** find simple paths from an anchor to an edge whose predicate matches the answer type, honoring relation cues for the first hop.
4. **Validate each step:** the fact exists and is valid at the query time (timelines for single-valued slots, validity windows otherwise), direction matches, no cycle, not conflicted, provenance present.
5. **Decide:** one distinct terminal value → answer with the full chain as evidence; several → report ambiguity/conflict, no pick; none → `insufficient_evidence` with the failed step recorded in `explain()` (not returned as evidence).
6. **Confidence:** evidence reliability and extraction confidence are the **minimum** over steps (weakest link).

Additionally, an answer-type guard stops the `exact` strategy from answering when the matched predicate cannot yield the requested type.

**Consequences.** No guessing across hops; every step traceable; cost bounded. Questions whose intermediate relations were never stated, or phrased outside the supported cue set, abstain (and are measured as such in the benchmark).
