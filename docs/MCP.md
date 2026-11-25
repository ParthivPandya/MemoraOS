# Using MemoraOS from coding agents (MCP)

`memoraos mcp` starts a Model Context Protocol server over stdio (protocol version `2024-11-05`, no extra dependencies). Any MCP client that can launch a stdio command can use it.

## What was verified

A scripted JSON-RPC session against `memoraos mcp` (Python 3.14, Windows) completed `initialize`, `tools/list`, a `memora_remember` call and a `memora_recall` call that returned the stored fact with its evidence. **The configuration snippets below follow each client's documented `mcpServers` format but have not been tested inside Claude Desktop, Cursor, VS Code or Codex CLI.** If a client rejects one, check that client's own MCP documentation.

## Install

Install from PyPI and make sure `memoraos` is on the `PATH` of the client:

```bash
pip install memoraos
memoraos --version
```

## Server settings

| Variable | Meaning |
|---|---|
| `MEMORAOS_USER_ID` | The user all tool calls run as. Fixed by configuration, never chosen by the model. Required. |
| `--data-dir <path>` (global CLI flag, before `mcp`) | Where the SQLite file lives. Default `./.memoraos` relative to the client's working directory, so set an absolute path. |
| `MEMORAOS_ENCRYPTION_KEY` | Optional passphrase for an encrypted database (Python 3.11+, `encryption` extra). |

## Client configuration

Most clients (Claude Desktop, Cursor and others) read a JSON file with an `mcpServers` object:

```json
{
  "mcpServers": {
    "memoraos": {
      "command": "memoraos",
      "args": ["--data-dir", "/absolute/path/to/memory", "mcp"],
      "env": { "MEMORAOS_USER_ID": "me" }
    }
  }
}
```

VS Code uses a `servers` object in `.vscode/mcp.json` with the same `command`, `args` and `env` fields. For Claude Code, the equivalent one-liner is:

```bash
claude mcp add memoraos --env MEMORAOS_USER_ID=me -- memoraos --data-dir /absolute/path/to/memory mcp
```

## Tools

| Tool | Purpose |
|---|---|
| `memora_remember` | Store text, optionally with `effective_at` (the date it became true). |
| `memora_recall` | Answer with evidence, or return `insufficient_evidence`. Supports `as_of` for time travel. |
| `memora_correct` | Replace a memory; history is kept. |
| `memora_forget` | Permanently delete a memory. |
| `memora_history` | Value timeline for a subject and predicate. |
| `memora_outcome` | Record that an action failed or succeeded (with reason and optional evidence reference). |
| `memora_warnings` | Recorded failures that match a planned action. |
| `memora_explain` | Show how an earlier recall was answered. |
| `memora_link` | Record an explicit causal link between two memories (`causes`, `solves`, `supersedes`, `blocked_by`). |
| `memora_lineage` | The explicit causal chain around a memory, with excerpts and content hashes. |
| `memora_replay` | Re-run an earlier recall with chosen memories removed (on a temporary copy) to see whether the answer depends on them. See [CAUSAL_AND_REPLAY.md](CAUSAL_AND_REPLAY.md). |

Retrieved memory is returned as data. A client should still treat it as untrusted text.

## Not provided

No automatic capture: the agent has to call `memora_remember` itself, or you instruct it to in the project's agent instructions. There is a Claude Code Stop hook (`memoraos hook install claude-code`, see [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md), not yet run in a real session) but none for Codex or Cursor. A LangChain retriever and a Mem0-shaped class exist ([INTEGRATIONS.md](INTEGRATIONS.md)); there is no LlamaIndex or CrewAI adapter.
