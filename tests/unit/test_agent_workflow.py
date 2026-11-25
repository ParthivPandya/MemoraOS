"""Hypothesis tier, outcome (negative) memory and the Claude Code hook."""

from __future__ import annotations

import json

from memoraos import hooks

U = "user_001"


def test_hypothesis_is_flagged_and_less_reliable_until_verified(mem):
    r = mem.remember("The cache layer uses Redis.", user_id=U, verification="hypothesis")
    res = mem.recall("Which cache layer is used?", user_id=U, use_cache=False)
    ev = [e for e in res.evidence if e.memory_id in r.memory_ids]
    assert ev and "hypothesis" in ev[0].flags and ev[0].source_reliability < 0.9
    mem.verify(r.memory_ids[0], "verified", user_id=U)
    res = mem.recall("Which cache layer is used?", user_id=U, use_cache=False)
    assert all("hypothesis" not in e.flags for e in res.evidence)


def test_failed_outcome_warns_and_a_later_success_clears_it(mem):
    mem.remember_outcome("upgrade the requests library to 3.0", "failed", reason="breaks the retry adapter", user_id=U)
    w = mem.outcome_warnings("should I upgrade requests library?", user_id=U)
    assert len(w) == 1 and w[0]["reason"] == "breaks the retry adapter" and not w[0]["verified"]
    assert mem.outcome_warnings("deploy the billing service", user_id=U) == []
    mem.remember_outcome("upgrade the requests library to 3.0", "succeeded", evidence_ref="ci-run-42", user_id=U)
    assert mem.outcome_warnings("upgrade requests library", user_id=U) == []


def test_outcome_with_evidence_ref_is_verified(mem):
    mem.remember_outcome("run migration 12", "failed", evidence_ref="logs/m12.txt", user_id=U)
    assert mem.outcome_warnings("run migration 12", user_id=U)[0]["verified"]


def test_hook_captures_last_exchange_as_redacted_hypotheses(mem, tmp_path):
    t = tmp_path / "t.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Deploy with key sk-abcdefghijklmnopqrstuvwxyz123456 please"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Deployed to staging."}, {"type": "tool_use", "name": "x"}]}},
    ]
    t.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    assert hooks.capture(mem, {"transcript_path": str(t), "session_id": "s1"}, U) == 2
    assert hooks.capture(mem, {"transcript_path": str(t), "stop_hook_active": True}, U) == 0
    rows = mem.db.query("SELECT original_content FROM memories")
    assert any("Deployed to staging" in r["original_content"] for r in rows)
    assert not any("sk-abcdefghij" in r["original_content"] for r in rows)
    assert {r["verification"] for r in mem.db.query("SELECT verification FROM sources")} == {"hypothesis"}


def test_hook_install_is_idempotent_and_reversible(tmp_path):
    s = tmp_path / ".claude" / "settings.json"
    s.parent.mkdir()
    s.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo keep"}]}]}}), encoding="utf-8")
    cmd = 'memoraos --data-dir "x" hook capture --user u'
    assert hooks.install_claude_code(s, cmd) and not hooks.install_claude_code(s, cmd)
    assert len(json.loads(s.read_text(encoding="utf-8"))["hooks"]["Stop"]) == 2
    assert hooks.uninstall_claude_code(s)
    assert json.loads(s.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo keep"


def test_cursor_and_codex_payloads_are_captured_as_hypotheses(mem):
    assert hooks.capture(mem, {"hook_event_name": "beforeSubmitPrompt", "prompt": "use postgres", "conversation_id": "c1"}, U, "cursor") == 1
    assert hooks.capture(mem, {"hook_event_name": "afterAgentResponse", "text": "ok, postgres", "conversation_id": "c1"}, U, "cursor") == 1
    assert hooks.capture(mem, {"hook_event_name": "stop", "status": "completed"}, U, "cursor") == 0
    assert hooks.capture(mem, {"hook_event_name": "Stop", "last_assistant_message": "done, key sk-abcdefghijklmnopqrstuvwx", "session_id": "s"}, U, "codex") == 1
    assert hooks.capture(mem, {"hook_event_name": "Stop", "last_assistant_message": None}, U, "codex") == 0
    assert hooks.capture(mem, {"hook_event_name": "Stop", "last_assistant_message": "x", "stop_hook_active": True}, U, "codex") == 0
    rows = mem.list_memories(user_id=U)
    assert len(rows) == 3
    assert all(r.verification == "hypothesis" for r in rows)
    assert not any("sk-abcdefghijklmnopqrstuvwx" in r.original_content for r in rows)


def test_hook_replies_match_each_tools_contract():
    assert hooks.reply("codex", {"hook_event_name": "Stop"}) == "{}"
    assert hooks.reply("codex", {"hook_event_name": "UserPromptSubmit"}) == ""
    assert json.loads(hooks.reply("cursor", {"hook_event_name": "beforeSubmitPrompt"})) == {"continue": True}
    assert hooks.reply("cursor", {"hook_event_name": "afterAgentResponse"}) == ""


def test_cursor_and_codex_install_keep_other_hooks_and_are_reversible(tmp_path):
    cmd = 'memoraos --data-dir "x" hook capture --user u --agent cursor'
    cur = tmp_path / "hooks.json"
    cur.write_text(json.dumps({"version": 1, "hooks": {"beforeSubmitPrompt": [{"command": "echo keep"}]}}), encoding="utf-8")
    assert hooks.install("cursor", cur, cmd) and not hooks.install("cursor", cur, cmd)
    cfg = json.loads(cur.read_text(encoding="utf-8"))
    assert [h["command"] for h in cfg["hooks"]["beforeSubmitPrompt"]][0] == "echo keep" and len(cfg["hooks"]["beforeSubmitPrompt"]) == 2
    assert len(cfg["hooks"]["afterAgentResponse"]) == 1
    assert hooks.uninstall("cursor", cur)
    assert json.loads(cur.read_text(encoding="utf-8"))["hooks"]["beforeSubmitPrompt"] == [{"command": "echo keep"}]

    cdx = tmp_path / "codex" / "hooks.json"
    assert hooks.install("codex", cdx, cmd.replace("cursor", "codex")) and not hooks.install("codex", cdx, cmd)
    cfg = json.loads(cdx.read_text(encoding="utf-8"))
    assert set(cfg["hooks"]) == {"UserPromptSubmit", "Stop"}
    assert cfg["hooks"]["Stop"][0]["hooks"][0]["type"] == "command"
    assert hooks.uninstall("codex", cdx) and not hooks.uninstall("codex", cdx)
