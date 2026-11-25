"""Coding-agent hooks (Claude Code, Cursor, Codex CLI): capture what was said as *hypotheses*, and inject memory.

Captured text is never trusted: it is stored with ``verification="hypothesis"`` (lower reliability, flagged on
recall) and passes through the normal secret redaction. Injection (``inject``) adds cited memory and recorded
failed attempts to the agent's context before it acts; it stores nothing. The payload fields and config layouts
follow each tool's published hook documentation; none of the three has been exercised in a live session of the
real tool (see ``docs/AGENT_WORKFLOW.md``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .context import build_context
from .engine import MemoryOS

MARKER = "memoraos"
MAX_CHARS = 2000
AGENTS = ("claude-code", "cursor", "codex")


def _text_of(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else message
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()
    return ""


def last_exchange(transcript: Path) -> list[tuple[str, str]]:
    """Last user and assistant text in a JSONL transcript (tool results and non-text blocks are skipped)."""
    last: dict[str, str] = {}
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        role = rec.get("type") or (rec.get("message") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        text = _text_of(rec.get("message", rec))
        if text:
            last[role] = text[:MAX_CHARS]
    return [(r, last[r]) for r in ("user", "assistant") if r in last]


def _event_turns(agent: str, payload: dict) -> list[tuple[str, str]]:
    """Cursor and Codex send one event per message, with the text in the payload (not in a transcript)."""
    event = payload.get("hook_event_name")
    if agent == "cursor":
        key = {"beforeSubmitPrompt": ("user", "prompt"), "afterAgentResponse": ("assistant", "text")}.get(event)
    else:
        key = {"UserPromptSubmit": ("user", "prompt"), "Stop": ("assistant", "last_assistant_message")}.get(event)
    text = payload.get(key[1]) if key else None
    return [(key[0], text.strip()[:MAX_CHARS])] if key and isinstance(text, str) and text.strip() else []


def capture(engine: MemoryOS, payload: dict, user_id: str, agent: str = "claude-code") -> int:
    """Store the text named by a hook payload as hypotheses; returns the number of memories written."""
    if agent not in AGENTS:
        raise ValueError(f"agent must be one of {', '.join(AGENTS)}")
    if payload.get("stop_hook_active"):
        return 0
    if agent == "claude-code":
        path = payload.get("transcript_path")
        turns = last_exchange(Path(path)) if path and Path(path).is_file() else []
    else:
        turns = _event_turns(agent, payload)
    for role, text in turns:
        engine.remember(
            f"{role}: {text}", user_id=user_id, source_type="conversation", verification="hypothesis", extract=False,
            origin=f"{agent}-hook", metadata={"session_id": payload.get("session_id") or payload.get("conversation_id"), "role": role},
        )
    return len(turns)


def reply(agent: str, payload: dict) -> str:
    """What the hook must print on stdout: Codex ``Stop`` requires JSON, Cursor's prompt hook expects ``continue``."""
    event = payload.get("hook_event_name")
    if agent == "codex" and event == "Stop":
        return "{}"
    if agent == "cursor" and event == "beforeSubmitPrompt":
        return '{"continue": true}'
    return ""


INJECT_TOOLS = "Bash|Write|Edit|MultiEdit"
MAX_QUERY_CHARS = 500


def _additional_context(event: str, text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, ensure_ascii=False)


def _tool_query(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    return str(tool_input.get("command") or tool_input.get("file_path") or "")[:MAX_QUERY_CHARS]


def inject(engine: MemoryOS, payload: dict, user_id: str, agent: str = "claude-code") -> str:
    """The hook's stdout that adds memory to the agent's context, or "" when there is nothing to add.

    ``UserPromptSubmit`` (Claude Code, Codex) gets cited evidence plus matching failed attempts for the prompt.
    Claude Code's ``PreToolUse`` gets failed-attempt warnings only, matched against the shell command or file path,
    so a failed fix is flagged before it is tried again. Cursor has no pre-prompt injection hook, so it is not
    supported here.
    """
    if agent not in ("claude-code", "codex"):
        raise ValueError("injection is supported for claude-code and codex only")
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        query = prompt.strip()[:MAX_QUERY_CHARS] if isinstance(prompt, str) else ""
        ctx = build_context(engine, query, user_id=user_id) if query else None
    elif event == "PreToolUse" and agent == "claude-code":
        query = _tool_query(payload)
        ctx = build_context(engine, query, user_id=user_id, with_evidence=False) if query else None
    else:
        return ""
    return _additional_context(event, ctx.text) if ctx else ""


# (layout, events): "nested" is {"hooks": {Event: [{"hooks": [{"type": "command", ...}]}]}}; "flat" is Cursor's
# {"version": 1, "hooks": {event: [{"command": ...}]}}
_SPECS = {
    "claude-code": ("nested", ("UserPromptSubmit", "PreToolUse", "Stop")),
    "codex": ("nested", ("UserPromptSubmit", "Stop")),
    "cursor": ("flat", ("beforeSubmitPrompt", "afterAgentResponse")),
}


def command_plan(agent: str, base: str, user_id: str, *, with_inject: bool = True) -> dict[str, tuple[str, str | None]]:
    """event -> (command, matcher) for ``install``. ``base`` is the program plus global options, e.g. ``memoraos --data-dir X``."""
    flag = "" if agent == "claude-code" else f" --agent {agent}"
    capture_cmd = f"{base} hook capture --user {user_id}{flag}"
    if agent == "claude-code":
        plan: dict[str, tuple[str, str | None]] = {"Stop": (capture_cmd, None)}
        if with_inject:
            cmd = f"{base} hook inject --user {user_id}"
            plan["UserPromptSubmit"] = (cmd, None)
            plan["PreToolUse"] = (cmd, INJECT_TOOLS)
        return plan
    if agent == "codex":
        # capture --inject recalls first and stores the prompt afterwards, so a prompt never retrieves itself
        prompt_cmd = f"{capture_cmd} --inject" if with_inject else capture_cmd
        return {"UserPromptSubmit": (prompt_cmd, None), "Stop": (capture_cmd, None)}
    return {event: (capture_cmd, None) for event in _SPECS[agent][1]}


def config_path(agent: str, *, project: bool = False) -> Path:
    base = Path.cwd() if project else Path.home()
    if agent == "claude-code":
        return base / ".claude" / "settings.json"
    if agent == "cursor":
        return base / ".cursor" / "hooks.json"
    if agent == "codex":
        home = Path.cwd() / ".codex" if project else Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        return home / "hooks.json"
    raise ValueError(f"agent must be one of {', '.join(AGENTS)}")


def _ours(command: str) -> bool:
    return MARKER in command and ("hook capture" in command or "hook inject" in command)


def _handlers(layout: str, group: dict) -> list[dict]:
    return [h for h in group.get("hooks", []) if isinstance(h, dict)] if layout == "nested" else [group]


def install(agent: str, path: Path, command: str | dict[str, tuple[str, str | None]], *, dry_run: bool = False) -> bool:
    """Add the hooks to ``path``; returns False when nothing changed.

    ``command`` is one command used for every event of the agent, or an ``event -> (command, matcher)`` plan. An
    existing MemoraOS handler for an event is updated in place when its command differs, so re-running with new
    options replaces it rather than duplicating it. Other tools' hooks are left alone.
    """
    layout, events = _SPECS[agent]
    plan = command if isinstance(command, dict) else {e: (command, None) for e in (("Stop",) if agent == "claude-code" else events)}
    data: dict = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if layout == "flat":
        data.setdefault("version", 1)
    hooks_cfg = data.setdefault("hooks", {})
    changed = False
    for event, (cmd, matcher) in plan.items():
        groups = hooks_cfg.setdefault(event, [])
        ours = [h for g in groups for h in _handlers(layout, g) if _ours(h.get("command", ""))]
        if ours:
            for h in ours:
                if h.get("command") != cmd:
                    h["command"] = cmd
                    changed = True
            continue
        handler: dict = {"command": cmd} if layout == "flat" else {"type": "command", "command": cmd}
        if agent == "codex":
            handler["timeout"] = 30
        if layout == "flat":
            groups.append(handler)
        else:
            groups.append({**({"matcher": matcher} if matcher else {}), "hooks": [handler]})
        changed = True
    if changed and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return changed


def uninstall(agent: str, path: Path) -> bool:
    if not path.is_file():
        return False
    layout, events = _SPECS[agent]
    data = json.loads(path.read_text(encoding="utf-8"))
    removed = False
    for event in events:
        groups = data.get("hooks", {}).get(event, [])
        kept = [g for g in groups if not any(_ours(h.get("command", "")) for h in _handlers(layout, g))]
        if len(kept) != len(groups):
            data["hooks"][event] = kept
            removed = True
    if removed:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return removed


def install_claude_code(settings_path: Path, command: str) -> bool:
    return install("claude-code", settings_path, command)


def uninstall_claude_code(settings_path: Path) -> bool:
    return uninstall("claude-code", settings_path)


def agent_home(agent: str) -> Path:
    """The directory whose existence says the agent is installed for this user."""
    if agent == "codex":
        return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return Path.home() / {"claude-code": ".claude", "cursor": ".cursor"}[agent]


def detect_agents() -> list[str]:
    return [a for a in AGENTS if agent_home(a).is_dir()]


def setup(
    user_id: str, data_dir: str | Path, agents: list[str] | None = None, *, project: bool = False, with_inject: bool = True,
    dry_run: bool = False, program: str = "memoraos",
) -> list[dict]:
    """Install the hooks of every (detected or named) agent against one shared data directory.

    ``data_dir`` is made absolute so every agent reads and writes the same store whatever its working directory.
    Cursor stays capture-only (it has no hook that can add context before a prompt).
    """
    base = f'{program} --data-dir "{Path(data_dir).expanduser().resolve()}"'
    names = agents if agents is not None else detect_agents()
    results = []
    for agent in names:
        if agent not in AGENTS:
            raise ValueError(f"agent must be one of {', '.join(AGENTS)}")
        path = config_path(agent, project=project)
        plan = command_plan(agent, base, user_id, with_inject=with_inject)
        changed = install(agent, path, plan, dry_run=dry_run)
        status = ("would change" if dry_run else "installed or updated") if changed else "already up to date"
        results.append({"agent": agent, "config": str(path), "events": sorted(plan), "status": status})
    return results
