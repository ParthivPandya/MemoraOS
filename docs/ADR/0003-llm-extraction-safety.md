# ADR-0003: LLM extraction is a proposal that must be verified against the source

**Status:** Accepted · 2026-11-17

**Context.** An LLM extractor can paraphrase well but can also invent facts, follow instructions hidden in documents, and emit invalid structures. The spec says an LLM is never authoritative and that all ingested content is untrusted.

**Decision.** `LLMExtractor` treats model output as a *proposal*:
1. The prompt states that the source is untrusted data. Sentences matching the injection detector are removed before the call.
2. Output must be JSON. Each proposed fact must include `span_text`, a **verbatim** quote from the source. The extractor (not the model) computes offsets; if the quote is not found, the fact is rejected.
3. Grounding: subject, object value and predicate cue must be supported by the quoted span (digits and named entities must appear). Otherwise rejected.
4. Predicates, entities, values and dates are re-normalized by deterministic code, not trusted from the model.
5. Failures (provider error, bad JSON, all facts rejected) are retried up to `extraction_max_attempts`, each attempt is recorded in `extraction_attempts`, and the deterministic `RuleBasedExtractor` is the fallback.
6. The model has no tools and no access to memory; its output can only add facts that quote the source.

**Consequences.** A hallucinated or injected fact cannot be stored unless the source literally contains the quoted text; even then it only restates what the source says. Extraction recall depends on the model; precision is bounded by validation. Real-model quality is **unmeasured** in this repository (only scripted fakes are tested).
