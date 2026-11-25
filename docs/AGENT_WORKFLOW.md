# Agent workflow: outcomes, hypotheses and coding-agent capture hooks

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
- MCP tools: `memora_outcome`, `memora_warnings`; `memora_recall` also returns `warnings`. REST: `POST /v1/outcomes`, `GET /v1/outcome-warnings`; both SDKs wrap them.
- There is no automatic expiry when a library version changes; record a new outcome instead.

## Capture hooks (Claude Code, Cursor, Codex CLI)

```bash
memoraos --data-dir ~/.memoraos hook install claude-code --user me      # ~/.claude/settings.json
memoraos --data-dir ~/.memoraos hook install cursor --user me           # ~/.cursor/hooks.json
memoraos --data-dir ~/.memoraos hook install codex --user me            # ~/.codex/hooks.json ($CODEX_HOME)
memoraos hook install <agent> --user me --project                       # project-level config in the current directory
memoraos hook uninstall <agent>
```

Each hook runs `memoraos hook capture --agent <agent>`, which reads the hook payload from stdin and stores the text
as hypotheses (`verification="hypothesis"`, origin `<agent>-hook`; secrets are redacted by the normal ingestion path,
each message is cut at 2,000 characters, `stop_hook_active` payloads are ignored, and a failure is written to stderr
instead of breaking the agent). Install is idempotent per event and leaves other hooks in the file alone.

| Agent | Events used | What is stored |
|---|---|---|
| Claude Code | `Stop` | last user message and last assistant text, read from the transcript file |
| Cursor | `beforeSubmitPrompt`, `afterAgentResponse` | the prompt and the agent response text from the payload |
| Codex CLI | `UserPromptSubmit`, `Stop` | the prompt and `last_assistant_message` from the payload |

Codex only runs a new hook after you review and trust it in `/hooks`; the installer prints that reminder. The Codex
`Stop` hook prints `{}` and Cursor's `beforeSubmitPrompt` hook prints `{"continue": true}`, as their contracts require.

What is verified: the install/uninstall merge for all three layouts, the capture logic and redaction, the stdout
replies, and a CLI run against hand-written payloads (`tests/unit/test_agent_workflow.py`). What is **not**: none of
the three has been run inside a real Claude Code, Cursor or Codex session. The config layouts and payload fields
follow each tool's published hook documentation and may change. Cursor's and Codex's other events are ignored.
Captured exchanges are raw text, so expect noise. Windsurf is not supported; use the MCP server ([MCP.md](MCP.md))
for it.
