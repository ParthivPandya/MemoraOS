# MemoraOS Next: implementation plan

Ordering follows the specification (P0 correctness and proof, then P1 differentiation, P2 ecosystem, P3 research). Gates are the specification's gates; the current position is in [NEXT_IMPLEMENTATION_STATUS.md](NEXT_IMPLEMENTATION_STATUS.md).

| Phase | Goal | Gate | State |
|---|---|---|---|
| 0 Audit | Verified status of every component | Every existing feature has a status | Done ([audit](NEXT_REPOSITORY_AUDIT.md)) |
| 1 Extraction | Real-provider extraction evaluation, golden sets, entity v2 | Real provider tested, deterministic fallback intact | Blocked on a local model; golden sets not started |
| 2 Retrieval and answerability | Raise answerable recall without more unsupported answers | Held-out recall up, false answers not up | **Not met**: policies built, benefit not confirmed |
| 3 Temporal and knowledge quality | Relative dates, recency-aware fallback, entity relationships | Historical, multi-hop and conflict tests pass | Not started; one defect found (stale fallback) |
| 4 Lifecycle and experience | States, controls, experience, skills | Originals preserved, derived records have provenance | Not started |
| 5 Governance and Memory CI | Change sets, approvals, contracts | Unauthorized shared change blocked; injected regression detected | Memory CI done; change sets not started |
| 6 Security and scale | Encryption, backup lifecycle, ANN | No known isolation or data-loss issue | Not started |
| 7 Ecosystem | SDKs, adapters, connectors, dashboard | A new developer can install, remember, recall, benchmark | Wheel install verified |
| 8 Evaluation | External datasets, competitor adapters, ablations | Reproduced and vendor numbers kept apart | Not started |
| 9 Release | Full tests, docs review, manual release approval | Every advertised feature verified | Not reached |

## Next steps, in order

1. Write an answerability V3 set from untouched documents; evaluate `balanced` and one stronger local embedder once.
2. Fix the stale documents-only fallback (recency or conflict) with out-of-order regression tests.
3. Golden extraction set (exact, paraphrase, negation, correction, multi-entity, numeric) with precision/recall; run it against a local LLM when one is available.
4. LoCoMo adapter, then LongMemEval, each with a disclosed judge and a held-out split.
5. Migration 3: entities, lifecycle states and user controls; then Change Sets on top of the event log.
6. Measure scale at 10^3, 10^4 and 10^5 memories before any ANN work.

Principle kept from the specification: fewer features done well. Features that cannot be verified here (real LLM providers, hosted APIs, competitor systems) stay labelled as unverified.
