# Agent workflow: outcomes, hypotheses and Claude Code capture

Three small features for coding agents. All are opt-in, none changes a benchmark default, and none has been measured
for accuracy. They are covered by unit tests with synthetic fixtures (`tests/unit/test_agent_workflow.py`).

## Hypothesis tier

`remember(..., verification="hypothesis")` stores text as an unchecked guess. Its source reliability is lowered by 0.2
and every `Evidence` from it carries the flag `hypothesis`. `verify(memory_id, "verified")` promotes it. A hypothesis
is **not excluded** from recall; it is flagged and down-weighted where reliability matters (conflict resolution).

## Outcome memory

```python
mem.remember_outcome("upgrade requests to 3.0", "failed", reason="breaks the retry adapter", user_id="u1")
mem.outcome_warnings("should I upgrade the requests library?", user_id="u1")
# [{"action": "upgrade requests to 3.0", "reason": "breaks the retry adapter", "verified": False, ...}]
```

- A record with `evidence_ref` (a test run id, a log path) is stored `verified`; without one it is a `hypothesis`.
  MemoraOS does not open or check the reference; it only records it.
- A warning appears when at least half of the recorded action's content words occur in the query (stemmed). This is
  lexical overlap, not understanding, so a paraphrase can be missed.
- A later `succeeded` outcome for a similar action clears the warning.
- MCP tools: `memora_outcome`, `memora_warnings`; `memora_recall` also returns `warnings`. There is no REST route yet.
- There is no automatic expiry when a library version changes; record a new outcome instead.

## Claude Code Stop hook

```bash
memoraos --data-dir ~/.memoraos hook install claude-code --user me      # ~/.claude/settings.json
memoraos hook install claude-code --user me --project                   # ./.claude/settings.json
memoraos hook uninstall claude-code
```

After each response the hook runs `memoraos hook capture`, which reads the hook payload from stdin and stores the
**last user message and last assistant text** from the transcript as hypotheses (secrets are redacted by the normal
ingestion path, each message is cut at 2,000 characters, and `stop_hook_active` payloads are ignored).

What is verified: the install/uninstall merge, the capture logic and redaction, and a CLI run against a hand-written
transcript. What is **not**: it has not been run inside a real Claude Code session, and the payload and transcript
formats are taken from Claude Code's documented hook interface and may change. Captured exchanges are raw text, so
expect noise. Cursor, Codex and Windsurf are not supported; use the MCP server ([MCP.md](MCP.md)) for those.