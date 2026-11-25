"""Claude Code hook integration: install a Stop hook and capture the last exchange as *hypotheses*.

Captured text is never trusted: it is stored with ``verification="hypothesis"`` (lower reliability, flagged on
recall) and passes through the normal secret redaction. Only Claude Code is supported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine import MemoryOS

MARKER = "memoraos"
MAX_CHARS = 2000


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


def capture(engine: MemoryOS, payload: dict, user_id: str) -> int:
    """Store the last exchange named by a hook payload; returns the number of memories written."""
    if payload.get("stop_hook_active"):
        return 0
    path = payload.get("transcript_path")
    if not path or not Path(path).is_file():
        return 0
    n = 0
    for role, text in last_exchange(Path(path)):
        engine.remember(
            f"{role}: {text}", user_id=user_id, source_type="conversation", verification="hypothesis", extract=False,
            origin="claude-code-hook", metadata={"session_id": payload.get("session_id"), "role": role},
        )
        n += 1
    return n


def install_claude_code(settings_path: Path, command: str) -> bool:
    """Add a Stop hook running ``command``. Idempotent; returns False if one is already installed."""
    data: dict = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    stops = data.setdefault("hooks", {}).setdefault("Stop", [])
    if any(MARKER in h.get("command", "") and "hook capture" in h.get("command", "") for g in stops for h in g.get("hooks", [])):
        return False
    stops.append({"hooks": [{"type": "command", "command": command}]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def uninstall_claude_code(settings_path: Path) -> bool:
    if not settings_path.is_file():
        return False
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    stops = data.get("hooks", {}).get("Stop", [])
    kept = [g for g in stops if not any("hook capture" in h.get("command", "") and MARKER in h.get("command", "") for h in g.get("hooks", []))]
    if len(kept) == len(stops):
        return False
    data["hooks"]["Stop"] = kept
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True
