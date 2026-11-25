"""Memory injection hooks and ``memoraos setup`` (tested on hand-written payloads and temp config folders)."""

from __future__ import annotations

import io
import json

import pytest

from memoraos import hooks
from memoraos.cli import main

U = "user_001"
BASE = 'memoraos --data-dir "D"'


def count(mem) -> int:
    return mem.db.one("SELECT COUNT(*) AS n FROM memories")["n"]


def test_prompt_hook_injects_cited_memory_and_stores_nothing(mem):
    mem.remember("The deploy region is eu-west-1.", user_id=U)
    before = count(mem)
    out = json.loads(hooks.inject(mem, {"hook_event_name": "UserPromptSubmit", "prompt": "What is the deploy region?"}, U))
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "UserPromptSubmit" and "eu-west-1" in spec["additionalContext"]
    assert count(mem) == before
    assert hooks.inject(mem, {"hook_event_name": "UserPromptSubmit", "prompt": "What is the CEO's shoe size?"}, U) == ""
    assert hooks.inject(mem, {"hook_event_name": "UserPromptSubmit", "prompt": ""}, U) == ""


def test_pre_tool_hook_warns_about_a_failed_attempt_without_recall_evidence(mem):
    mem.remember_outcome("run alembic downgrade base on production", "failed", reason="dropped the users table", user_id=U)
    mem.remember("The alembic downgrade command is documented in the runbook.", user_id=U)
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "alembic downgrade base"}}
    out = json.loads(hooks.inject(mem, payload, U))
    text = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse" and "dropped the users table" in text
    assert "runbook" not in text and "permissionDecision" not in json.dumps(out)
    assert hooks.inject(mem, {**payload, "tool_input": {"command": "ls"}}, U) == ""
    assert hooks.inject(mem, {**payload, "tool_input": "oops"}, U) == ""


def test_inject_is_not_available_for_cursor_and_ignores_other_events(mem):
    with pytest.raises(ValueError):
        hooks.inject(mem, {"hook_event_name": "beforeSubmitPrompt", "prompt": "x"}, U, "cursor")
    assert hooks.inject(mem, {"hook_event_name": "Stop"}, U) == ""
    assert hooks.inject(mem, {"hook_event_name": "PreToolUse", "tool_input": {"command": "x"}}, U, "codex") == ""


def test_claude_install_adds_prompt_and_tool_hooks_and_replaces_on_change(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]}}), encoding="utf-8")
    assert hooks.install("claude-code", s, hooks.command_plan("claude-code", BASE, "u"))
    assert not hooks.install("claude-code", s, hooks.command_plan("claude-code", BASE, "u"))
    cfg = json.loads(s.read_text(encoding="utf-8"))["hooks"]
    assert set(cfg) == {"PreToolUse", "UserPromptSubmit", "Stop"}
    assert [g.get("matcher") for g in cfg["PreToolUse"]] == ["Bash", hooks.INJECT_TOOLS]
    assert cfg["UserPromptSubmit"][0]["hooks"][0]["command"].endswith("hook inject --user u")
    assert cfg["Stop"][0]["hooks"][0]["command"].endswith("hook capture --user u")
    assert hooks.install("claude-code", s, hooks.command_plan("claude-code", BASE, "v"))
    cfg = json.loads(s.read_text(encoding="utf-8"))["hooks"]
    assert len(cfg["UserPromptSubmit"]) == 1 and cfg["UserPromptSubmit"][0]["hooks"][0]["command"].endswith("--user v")
    assert hooks.uninstall("claude-code", s)
    assert json.loads(s.read_text(encoding="utf-8"))["hooks"]["PreToolUse"] == [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}]


def test_no_inject_plans_and_codex_prompt_hook():
    assert set(hooks.command_plan("claude-code", BASE, "u", with_inject=False)) == {"Stop"}
    plan = hooks.command_plan("codex", BASE, "u")
    assert plan["UserPromptSubmit"][0].endswith("--agent codex --inject") and plan["Stop"][0].endswith("--agent codex")
    assert not hooks.command_plan("codex", BASE, "u", with_inject=False)["UserPromptSubmit"][0].endswith("--inject")
    assert all("inject" not in c for c, _ in hooks.command_plan("cursor", BASE, "u").values())


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for d in (".claude", ".codex"):
        (home / d).mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return home


def test_setup_detects_agents_uses_one_absolute_data_dir_and_dry_run_writes_nothing(fake_home, tmp_path):
    assert hooks.detect_agents() == ["claude-code", "codex"]
    dry = hooks.setup("u", tmp_path / "brain", dry_run=True)
    assert [r["status"] for r in dry] == ["would change", "would change"] and not (fake_home / ".claude" / "settings.json").exists()
    res = hooks.setup("u", tmp_path / "brain")
    assert [r["agent"] for r in res] == ["claude-code", "codex"]
    claude = json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
    assert str((tmp_path / "brain").resolve()) in claude["Stop"][0]["hooks"][0]["command"]
    assert (fake_home / ".codex" / "hooks.json").is_file() and not (fake_home / ".cursor").exists()
    assert [r["status"] for r in hooks.setup("u", tmp_path / "brain")] == ["already up to date"] * 2
    with pytest.raises(ValueError):
        hooks.setup("u", tmp_path, ["windsurf"])


def test_cli_hook_inject_and_codex_capture_inject_recall_before_storing(tmp_path, monkeypatch, capsys):
    data = str(tmp_path / "d")
    assert main(["--data-dir", data, "remember", "The deploy region is eu-west-1.", "--user", U]) == 0
    capsys.readouterr()
    prompt = {"hook_event_name": "UserPromptSubmit", "prompt": "What is the deploy region?", "session_id": "s"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(prompt)))
    assert main(["--data-dir", data, "hook", "inject", "--user", U]) == 0
    assert "eu-west-1" in json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    new = {**prompt, "prompt": "We now deploy to ap-south-1."}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(new)))
    assert main(["--data-dir", data, "hook", "capture", "--user", U, "--agent", "codex", "--inject"]) == 0
    out = capsys.readouterr().out
    assert "ap-south-1" not in out
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert main(["--data-dir", data, "hook", "inject", "--user", U]) == 0 and capsys.readouterr().out == ""
    assert main(["--data-dir", data, "export", "--user", U]) == 0
    assert "user: We now deploy to ap-south-1." in capsys.readouterr().out


def test_cli_proxy_refuses_a_public_address_without_the_override(tmp_path, capsys):
    pytest.importorskip("uvicorn")
    assert main(["--data-dir", str(tmp_path), "proxy", "--target", "http://x", "--user", U, "--host", "0.0.0.0"]) == 2
    assert "refusing to listen" in capsys.readouterr().err
