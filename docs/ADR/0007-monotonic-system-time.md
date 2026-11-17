# ADR-0007: System time is strictly monotonic

**Status:** Accepted · 2026-11-17 (implemented during the audit)

**Context.** CI failed intermittently on Windows (`test_temporal_memory`). Facts stored back-to-back received identical `recorded_at` values on a ~15 ms clock, and the timeline tie-break used the random fact id, so the "latest" value was chosen at random.

**Decision.** `Store.now()` never returns a value ≤ the previous one (1 µs bump). Timelines sort stably on `(effective time, recorded_at)` and keep insertion order for ties. Recall, history and change-log use the same source for "now" so recorded facts are never "in the future".

**Consequences.** `recorded_at` can run up to microseconds ahead of the wall clock under bursts. As-of queries remain correct because they compare against the same monotonic stamps. Covered by two regression tests; benchmark digest unchanged.
