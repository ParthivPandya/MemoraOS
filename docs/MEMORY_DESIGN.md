# Memory Design

## Memory record

Every stored memory preserves: unique id, **original content** (never discarded; secrets are redacted before storage), normalized content, source id and type, `created_at`, optional `effective_at`, `updated_at`, category, extraction `confidence`, embedding reference, scope (level, id, user), version history, reliability and verification (via its source), `derived` flag, `mention_count`, `importance`.

Long inputs are chunked (paragraph/sentence aware, default 800 chars, 100 overlap). Each chunk is one memory; all chunks share one `sources` row holding the full original text.

## Memory types

| Type | Assigned when | Used by |
|---|---|---|
| Episodic | Conversation source, or text describing events (yesterday, we decided, failed…) | `episodic` strategy: time windows, "before/after X" anchoring |
| Semantic | Default; facts, preferences, definitions | exact/temporal fact lookup, hybrid retrieval |
| Procedural | Step lists, "to deploy:", imperative runs, inline code | `procedural` strategy returns the whole procedure |
| Temporal | Any fact with valid time | Bitemporal fact timelines ([TEMPORAL_MEMORY.md](TEMPORAL_MEMORY.md)) |
| Relational | Relation facts + entity co-mentions | `graph` strategy (multi-hop paths) |
| Latent | Optional | Experimental ([LATENT_MEMORY.md](LATENT_MEMORY.md)) |

The category is a heuristic and can be overridden: `remember(..., category="procedural")`.

## Facts and extraction

`extract_facts` is deterministic and rule-based: possessives (`X's salary is …`), first person (`my … is …`), `the P of X is …`, ~25 verb patterns (works at, lives in, uses, leads, depends on, is hosted in, …, including passive "led by"), list splitting (`uses A and B`), and date phrases (`in 2024`, `as of March 2026`, `from 2022 to 2024`, ISO dates, `YYYY-MM`). Questions and injection-like sentences yield no facts. Explicit facts can be supplied via `remember(..., facts=[{subject, predicate, object, valid_from}])` or `remember_json`.

**Known limits:** English only, declarative sentences, no coreference, no negation handling. Inverted ("C is where P lives") and indirect phrasings are not extracted (measured in `paraphrase_robustness`). When extraction misses, the passage retrieval path still applies, but its evidence checks may abstain.

**Slots.** A predicate is *single-valued* (a new value supersedes the old; e.g. `salary`, `database`, `owner`, any predicate whose head word is in a list like framework/version/status) or *multi-valued* (`uses`, `prefers`). `uses`/`depends_on` with a version suffix become per-product slots (`uses:angular`) so `Angular 16 → Angular 19` is a version change.

## Confidence — five separate signals

Never collapsed into one number (`RecallResult.confidence`):

1. `extraction_confidence` – how sure the extractor was about the fact (rule pattern, explicit = 1.0)
2. `source_reliability` – by source type (user statement 0.9, structured 0.85, conversation 0.75, document 0.7, external 0.6, inferred 0.4, consolidation 0.3); ±: verified +0.1, disputed −0.3
3. `temporal_validity` – current / historical / conflicted / undated / not applicable
4. `retrieval_relevance` – ranking score of the best candidate (0–1)
5. `evidence_coverage` – fraction of question terms covered by the evidence

plus `route_confidence` for the routing decision.

## Evidence and support

An answer is `answered` only if its evidence is **supported**: for fact answers, a matching, currently valid fact; for passage answers, at least 50% of the question's content terms are covered, the named entities appear, and (when the question has ≥2 non-entity terms) the asked-about attribute word appears in the evidence. Otherwise: `insufficient_evidence`, with near-misses recorded in `explain()` but **not returned as evidence**. Sentences that look like prompt injection are never selected as answers.

## Duplicates and corrections

- Exact duplicate text (same scope): no new memory; `mention_count` increments and the new source is attached in `memory_provenance`. Each assertion is still an event, so a repeated old value can restore an earlier value on the timeline.
- Near duplicates: linked (`duplicate_of`) by consolidation; originals stay; search collapses them to the canonical memory; rollback unlinks.
- `correct(memory_id, new_content)`: new version row, old facts **retracted** (kept for as-of queries), derived summaries of the old text deactivated. `forget` hard-deletes.

## Consolidation

See [ARCHITECTURE.md](ARCHITECTURE.md) and `consolidation/engine.py`. Per run: near-duplicate links, conservative alias merges (`Parth` → `Parth Pandya` only when exactly one two-token entity starts with that token and they are never co-mentioned; ambiguous pairs are *proposed*, not merged), entity/theme clusters of ≥3 memories → one **derived** summary (reliability 0.3, linked `derived_from` to every source, carries no facts), importance scores, reports on corroborated facts and outdated values. Modes: manual, incremental (watermark), dry-run, scheduled thread. Rollback removes the run's summaries, aliases and links. **Originals and facts are never modified**; the test-suite and benchmark assert this.
