# Temporal Memory and the Truth Engine

## Two time axes

| Axis | Columns | Meaning |
|---|---|---|
| Valid time | `valid_from`, `valid_until` | When the fact was true in the world (from the text: "in 2024", "as of March 2026", "from 2022 to 2024", or `effective_at`) |
| System time | `recorded_at`, `retracted_at` | When MemoraOS learned / withdrew it |

Nothing is overwritten. A new salary adds a fact; a correction sets `retracted_at` on the old facts of that memory. "What did we know on D" filters `recorded_at ≤ D AND (retracted_at IS NULL OR retracted_at > D)` and reads memory text from `memory_versions` as of D, so later knowledge cannot leak (tested in scenario J).

## Timeline construction (`truth/timeline.py`)

Facts of one `(subject, slot)` are ordered by effective time (valid_from, else recorded_at), consecutive identical values merge into **runs**, and consecutive different runs are related by these rules:

1. Earlier run has an explicit end date ≤ later start → **update**.
2. Both explicitly dated: later date → **update**; same date → **conflict**.
3. Otherwise (at least one undated), in order:
   a. same product, different version (`Angular 16 → 19`) → **possible_version_change** (later wins; reported)
   b. later value has an effective date after the earlier one was recorded → update
   c. both self-reported (user statement / conversation) → later supersedes
   d. one value verified / the other disputed → verified wins (reported)
   e. reliability differs by ≥ 0.2 → more reliable wins (reported; a weaker *later* value is kept out of the current state)
   f. else → **conflict**: both values stay "current", the answer says the memory does not establish which is right, and `status="conflict"`.

An unresolved conflict closes when a later, clearly ordered value arrives; the contradiction record stays (`resolved=True`, with `since` = when it began).

## Question handling

| Question | Behaviour |
|---|---|
| "current …" / no time | value valid now |
| "… in 2025", "as of March 2026" | value valid then (period overlap) |
| "previous … / before it changed" | the value of the group before the current one |
| "history / timeline" | all values with effective dates |
| `as_of=` argument | everything above, but only using what was recorded by that instant |

`RecallResult.timeline` returns every value with status (current / historical / conflicted), valid dates (or `inferred_start` when ordered only by recording time), recorded time and reliability.

## What is *not* handled

Relative dates in stored text ("last month"), time zones other than UTC, uncertain/approximate dates, and facts whose validity is implied rather than stated. Date-only `valid_until` means "through the end of that day".

## Audit trail

`events` is append-only with `hash = SHA256(prev_hash | ts | tenant | type | memory_id | payload)`. `MemoryOS.verify_audit_chain()` recomputes it; editing a row breaks the chain (tested). Hard deletion removes content from every table but keeps a content-free `memory.forgotten` event.

APIs: `history(memory_id)`, `history(subject, predicate)`, `snapshot(as_of)`, `changes(since, until)` with before/after text, `contradictions()`, `explain(recall_id)`.
