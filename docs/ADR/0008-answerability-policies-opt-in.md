# ADR-0008: Answerability policies are opt-in until an independent set confirms them

**Status:** Accepted · 2026-11-18

**Context.** On real documentation MemoraOS misses 22 of 46 answerable questions; for 15 the right section was retrieved and refused by a lexical support check. Section-level and (with a neural embedder) semantic support were built to recover them. They improved the design set (dev) but did not reliably improve the independent validation set; see `docs/NEXT_ANSWERABILITY.md`.

**Decision.** Add `Settings.answerability` with `strict` (the v0.2 behaviour) as the default and `balanced`, `high_recall`, `extractive_only` as opt-in. Thresholds were frozen from dev results before the validation run. No default changes until a fresh V3 set shows a recall gain whose interval excludes no change, with the unsupported-answer rate not higher.

**Rejected.** A hard "unknown word" refusal (11 of 30 answerable dev questions contain such a word); lowering `min_anchor_coverage` globally (published trade-off curve, unsupported answers rise); adding new answer statuses (would change the public API and the TypeScript SDK for no measured gain).

**Consequences.** Users can opt in and see the trade-off; the default product claim is unchanged; the evidence is in the repository. The thresholds are tied to one corpus and one small embedder and must be re-measured for others.
