"""Coding-agent hooks (Claude Code, Cursor, Codex CLI): capture what was said as *hypotheses*.

Captured text is never trusted: it is stored with ``verification="hypothesis"`` (lower reliability, flagged on
recall) and passes through the normal secret redaction. The payload fields and config layouts follow each tool's
published hook documentation; none of the three has been exercised in a live session of the real tool (see
``docs/AGENT_WORKFLOW.md``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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


# (layout, events): "nested" is {"hooks": {Event: [{"hooks": [{"type": "command", ...}]}]}}; "flat" is Cursor's
# {"version": 1, "hooks": {event: [{"command": ...}]}}
_SPECS = {
    "claude-code": ("nested", ("Stop",)),
    "codex": ("nested", ("UserPromptSubmit", "Stop")),
    "cursor": ("flat", ("beforeSubmitPrompt", "afterAgentResponse")),
}


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
    return MARKER in command and "hook capture" in command


def _commands(layout: str, group: dict) -> list[str]:
    return [h.get("command", "") for h in group.get("hooks", [])] if layout == "nested" else [group.get("command", "")]


def install(agent: str, path: Path, command: str) -> bool:
    """Add the capture hook to ``path``. Idempotent per event; returns False if every event already had it."""
    layout, events = _SPECS[agent]
    data: dict = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if layout == "flat":
        data.setdefault("version", 1)
    hooks_cfg = data.setdefault("hooks", {})
    changed = False
    for event in events:
        groups = hooks_cfg.setdefault(event, [])
        if any(_ours(c) for g in groups for c in _commands(layout, g)):
            continue
        handler: dict = {"command": command} if layout == "flat" else {"type": "command", "command": command}
        if agent == "codex":
            handler["timeout"] = 30
        groups.append(handler if layout == "flat" else {"hooks": [handler]})
        changed = True
    if changed:
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
        kept = [g for g in groups if not any(_ours(c) for c in _commands(layout, g))]
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
