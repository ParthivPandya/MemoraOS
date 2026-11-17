# Extraction (v0.2)

Original text is always preserved. Facts are a derived, rebuildable index over it (`MemoryOS.rebuild_facts()`).

## Modes (`Settings.extraction_mode`)

| Mode | Behaviour |
|---|---|
| `rules` (default) | Deterministic English rules. Offline, no key, same output every time. |
| `llm` | A chat model proposes facts; validated proposals are stored. If the model fails or returns invalid JSON, rules run instead. |
| `hybrid` | Rules and LLM both run. Every rule fact is kept; validated LLM facts that rules did not find are added. When they disagree on the same span, the rule fact wins and the disagreement is logged. |

With `llm` or `hybrid` but no chat provider, the engine stays on rules.

## What the rules cover

Negation (`does not`, `isn't`, `never`, `no longer`) → `polarity = negated`; `Correction:`/`Update:` prefixes; conjoined clauses and compound subjects become separate facts, each with its own source span; inverted phrasing ("X is where Y lives"); `makes <money>`; owner-less attribute statements ("The budget is …": subject `unspecified`, confidence 0.5). The sentence patterns are grammar illustrations of what the rules parse, not stored data; `tests/unit/test_extraction.py` exercises each.

**Not covered** (needs the LLM path): indirect or implicit statements ("You can reach <person> in <city> these days").

## Negation semantics

Negated facts are stored (inspect them with `MemoryOS.facts()`), never answer a positive question, and end the validity of an earlier affirmation of the same subject/predicate/value that was recorded before them. A memory whose only facts are negations is not quoted as a passage answer.

## Value normalization

`extraction.values.parse_value` canonicalises money (`lakh`/`lac`/`crore`/`k`/`m`/`bn`, `LPA`, `₹ $ € £ Rs INR`, annual/monthly/hourly). Compensation predicates annualise monthly figures. Equality needs the same amount, currency and period. An unknown currency or period stays unknown (`?`) and never merges with a known one. Embedding similarity is never used to merge facts. Lakh/crore/LPA imply INR unless a currency is given.

## LLM safety rails (`extraction/llm.py`, `extraction/validate.py`)

1. Sentences that look like prompt injection (and questions) are removed **before** the model sees the text; text is sent inside `<memory>` tags as data.
2. The model returns `span_text`; offsets are computed by us and must exist verbatim in the memory.
3. Every proposal is rejected unless: the object (and any number or capitalised token in it) occurs in the span; the subject occurs in the text (or the span is first person); a lexical cue for the predicate occurs in the span (`extraction_strict`); negation in the span matches `polarity`; no field contains injection text; fields are ≤ 200 chars.
4. Dates are re-derived from the span, predicates re-normalised, confidence capped at 0.85; at most 20 facts per chunk.
5. Every run is recorded in `extraction_attempts` (`ok`, `partial`, `invalid_json`, `provider_error`, `skipped`, `fallback`) with rejection reasons, so failures are visible and retryable.
6. Identical text is not sent to the model twice.

**Unmeasured:** these rails are tested with scripted fake models, including hallucinated, malformed and injected output. Extraction quality of any real model is not benchmarked.

## Storage

`facts` columns added in migration 2: `polarity`, `extraction_method`, `extractor_version`, `source_span_start/end` (offsets into `memories.original_content`), `value_num`, `value_unit` (period), `value_currency`. v0.1 rows read as `rules-v1`/`affirmed`; their object keys are upgraded on read, and `rebuild_facts()` re-derives them. Old facts are retracted, not deleted, so time travel still works.
