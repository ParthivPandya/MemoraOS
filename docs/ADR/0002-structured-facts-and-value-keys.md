# ADR-0002: Structured facts, canonical value keys, and source spans

**Status:** Accepted · 2026-11-17

**Context.** `32 LPA`, `32 lakhs annually`, `32 lakh rupees` and `₹32 lakh per annum` are four different strings to v0.1, so equivalent statements from documents are reported as conflicts (audit F6). Negation (F3), corrections (F4), conjunctions (F5) and bare attribute statements (F7) also produce wrong or missing facts.

**Decision.**
- Introduce typed Pydantic models (`StructuredFact`, `SourceSpan`, `ExtractionResult`) as the validated extraction output. v0.1's `ExtractedFact` stays as the persistence-facing dataclass, with optional new fields.
- Parse values into `(kind, number, currency, period)` and derive a canonical `value_key` such as `money:INR:annual:3200000`. New facts store `object_key = value_key` when a value parses, else the normalized text. The extracted wording stays in `object`.
- Two facts are the same only if subject key, predicate and `object_key` agree. Unknown currency or period never merges. Embedding similarity is never used to merge facts.
- Persist `polarity` (`affirmed` | `negated`). Negated facts are stored (provenance) but excluded from positive resolution and never create contradictions.
- Persist a source span (`start`, `end`) that indexes into `memories.original_content`, plus `extraction_method` and `extractor_version`.

**Consequences.** False conflicts from unit variants disappear; wording is preserved; spans are verifiable (`original_content[start:end] == text`). Salary-like periods are annualized (monthly × 12); this is documented and applies only to compensation predicates.

**Rejected.** Replacing `object` with a JSON object (breaks v0.1 readers and the stored wording); merging by embedding similarity (violates the spec).
