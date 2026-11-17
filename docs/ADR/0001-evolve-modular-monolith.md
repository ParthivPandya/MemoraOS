# ADR-0001: Evolve the v0.1 modular monolith; additive storage changes only

**Status:** Accepted · 2026-11-17

**Context.** The spec asks to improve v0.1 without unnecessary rewrites and to keep every v0.1 database usable. The audit found the architecture sound; the defects are in extraction, normalization and multi-hop answering, not in the storage or API structure.

**Decision.** Keep the modular monolith and SQLite. Add packages (`extraction/`, `fusion/`) and extend tables with `ADD COLUMN` plus defaults and new tables. No renames, no drops, no data rewrites inside a migration. Legacy provider objects keep working through adapters. Derived data (facts) can be rebuilt from preserved originals by an explicit `rebuild_facts()`.

**Consequences.** Old and new facts coexist; old facts keep v0.1 keys until rebuilt. Migration risk is low and testable with a real v0.1 file. Some v0.1 shapes (for example `object_key`) carry two meanings (normalized text or canonical value key), which is documented in the schema.

**Conflict noted.** The spec suggests a field `object: {value, currency, unit}`. v0.1 stores `object` as text. We keep the text column (the extracted wording, which the spec also says to preserve) and add typed columns beside it instead of replacing it.
