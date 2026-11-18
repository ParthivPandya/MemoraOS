# MemoraOS Next: architecture changes

The architecture stays a modular monolith on SQLite ([ARCHITECTURE.md](ARCHITECTURE.md), [V02_ARCHITECTURE.md](V02_ARCHITECTURE.md)). This work added three pieces and changed no storage schema.

```
 memoraos ci  ──► contracts.py  (load, validate, run in a fresh in-memory engine, compare)
                        │
                        ▼
                  MemoryOS.recall ──► Recaller._passages
                                         ├─ strict sentence-level support            (unchanged default)
                                         ├─ _section_answer   (policy: lexical embedder)
                                         └─ _semantic_answer  (policy: neural embedder only)

 benchmarks/  failures.py ─► per-question cause from retrieval_log
              answerability.py ─► Wilson CIs, recall, unsupported rate, Brier/ECE, V2 validation set
```

Boundaries and rules:

- **Support is decided in one place** (`Recaller._passages`). The new paths run only when sentence-level support fails, only outside chain questions (those stay with evidence fusion), and never bypass the answer-type, named-entity and named-version guards.
- **The semantic path is neural-only.** It checks that the configured embedder is not the lexical hashing one, because cosine over hashed features is not meaning. Sentence vectors live in a bounded in-process cache and are never written to the store.
- **Memory CI is a client of the public engine API**, not of storage, so a contract exercises the same path an application does. File sources are confined to the contract or working directory.
- **Defaults do not change.** `answerability="strict"` reproduces v0.2 exactly (synthetic digest unchanged).

Decisions: [ADR-0008](ADR/0008-answerability-policies-opt-in.md), [ADR-0009](ADR/0009-memory-ci-contracts.md).
