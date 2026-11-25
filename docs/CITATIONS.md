# Verifiable citations

Every piece of evidence returned by `recall` says where its quote sits in the stored text, so an answer can be checked
instead of trusted.

## What is in each `Evidence`

| Field | Meaning |
|---|---|
| `memory_id`, `source_id` | the stored memory and the original source it came from |
| `excerpt` | the quoted text |
| `span_start`, `span_end` | offsets of the quote inside the memory's stored text (`null` if the excerpt is not a verbatim span) |
| `quote_sha256` | SHA-256 of the quoted span |

## Verifying

```python
res = mem.recall("Which address does the API bind to by default?", user_id="u1")
report = mem.verify_citations(res.evidence, user_id="u1")
# {"valid": True, "verified": 2, "total": 2, "results": [{"memory_id": ..., "status": "verified"}, ...]}
```

REST: `POST /v1/verify-citations` with `{"user_id": "...", "evidence": [...]}` (needs the `read` role).

Statuses: `verified` (quote found at the cited offsets, hash matches, and it occurs in the retained original source),
`unlocated` (the excerpt was never a verbatim span), `quote_changed` (memory text edited since), `source_mismatch`,
`memory_missing`. `valid` is true only if every item is `verified`.

## What this does and does not show

- It proves a quote exists, unchanged, in what MemoraOS stored. It does **not** prove the quote supports the answer, and
  it does not prove the source itself is true.
- The source comparison collapses whitespace, because the chunker re-flows line breaks and list markers, so a memory
  is not always byte-identical to its source.
- A memory that is later corrected reports `quote_changed` for old citations. That is intended: the cited text is gone.

## Measured on the real-document benchmark

`python -m benchmarks.citations` (46 answerable questions, corpus sha `f7f72a5718130f61...`). Mechanical checks only:

| Measure | Result |
|---|---|
| Answerable questions answered | 33 / 46 |
| Answers whose citations all verify (none failing) | 33 / 33 |
| Answers with at least one `unlocated` citation | 3 |
| Answers where a cited quote contains the gold string | 27 / 33 |
| Correct answers where a cited quote contains the gold string | 24 |

Verification success is a check of storage integrity, not of answer accuracy; this feature does not change accuracy.