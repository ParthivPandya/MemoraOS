# ADR-0009: Memory CI contracts are plain data run through the public engine

**Status:** Accepted · 2026-11-18

**Context.** Changes to extraction, embeddings, routing or configuration can silently change what memory answers. Developers need the discipline used for application code: written expectations, a command, an exit code and a regression report.

**Decision.** A contract is a JSON (optionally YAML) document with sources and assertions. `memoraos.contracts` runs it in a fresh in-memory engine through `MemoryOS.remember/recall` (the public API) and compares two result files. Exit code 0 means pass without regression, 1 a failure or regression, 2 a malformed contract. Source files are confined to the contract or working directory. Contracts carry no credentials; refusal tests are written as questions whose answer must be absent.

**Rejected.** Running against storage directly (would not exercise the real path); a mandatory YAML dependency; fuzzy or LLM-judged matching (non-deterministic); a hosted service.

**Consequences.** Deterministic, offline, dependency-free. Substring matching can pass on an incidental match (mitigated with `forbidden_answer`). Automatic triggers and CLI provider selection are not part of this decision and remain open.
