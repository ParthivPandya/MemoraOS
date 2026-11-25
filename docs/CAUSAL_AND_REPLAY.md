# Causal links, counterfactual replay and `memoraos sleep`

All three are small, deterministic tools. None is benchmarked, and none of them learns anything.

## Explicit causal links

```python
mem.link(fix_id, failure_id, "solves", user_id="me")      # fix solves failure
mem.link(failure_id, outage_id, "causes", user_id="me")
mem.lineage(outage_id, user_id="me", direction="up")     # who caused / solved what led here
mem.why(recall_id, user_id="me")                          # explain() plus the lineage of each cited memory
```

CLI: `memoraos link <src> <kind> <dst> --user me`, `memoraos lineage <id> --user me [--direction up|down|both]`. REST: `POST /v1/links`, `GET /v1/lineage/{id}`. MCP: `memora_link`, `memora_lineage`.

- Kinds: `causes`, `solves`, `supersedes`, `blocked_by` (`src <kind> dst`). Self-links are rejected.
- **Edges exist only if you create them.** MemoraOS does not infer causality from text, and a missing edge means "nobody recorded one", not "no cause".
- Each lineage node has the memory's excerpt, version, `effective_at` and `content_sha256` (SHA-256 of the full stored text), so a chain can be checked against the evidence.
- Memories the caller cannot see are skipped, never revealed. Forgetting a memory removes its edges. Linking and unlinking are written to the audit chain.
- Edges are stored in `memory_links` with type `causal:<kind>`; no schema change.

## Counterfactual replay

```python
res = mem.recall("What is the customer plan?", user_id="me")
mem.replay(res.recall_id, user_id="me", exclude=[memory_id])     # without that memory
mem.replay(res.recall_id, user_id="me", leave_one_out=True)      # each cited memory in turn (max_runs=8)
```

CLI: `memoraos replay <recall_id> --user me --exclude <id> ...` or `--leave-one-out`. REST: `POST /v1/replay`. MCP: `memora_replay`.

How it works: the database is copied to a temporary directory (`backup`), the excluded memories are hard-deleted **from the copy**, and the logged query is re-run there (with the logged `as_of`). The live store is never modified, and the copy is discarded. The report contains:

- `logged`: the answer recorded at the time;
- `baseline`: the same query run now on an unmodified copy;
- `runs[]`: for each exclusion, the new answer and status, and `answer_changed` / `status_changed` against the baseline;
- `baseline_matches_logged`: `false` means the data changed since the recall, so compare `runs` with `baseline`, not with `logged`.

Limits: it runs at **user scope** (agent, session and project scopes are not recorded in the retrieval log); the cost is a full copy of the database per run, so it suits small and medium stores; deleting a memory also deletes facts and derived summaries it produced, which is the intent. **There is no dashboard view for it**; the Next.js dashboard was not changed.

## `memoraos sleep`

```bash
memoraos sleep --user me [--expire-hypotheses-days 30] [--no-consolidate] [--dry-run]
```

One maintenance pass that runs existing steps: `consolidate` (reversible, see `rollback_consolidation`), a check of the audit hash chain, a count of open contradictions, and, only if asked, marking unconfirmed `hypothesis` memories older than N days as `disputed` (they stay readable and in history). `--dry-run` reports what would change. It does not score "surprise" or run any model, and it is not scheduled automatically (`MemoryOS.start_scheduler` is separate).
