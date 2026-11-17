import io
import json

import pytest

from memoraos.mcp.server import TOOLS, McpServer


@pytest.fixture
def server(mem):
    return McpServer(mem, "mcp_user")


def rpc(server, method, params=None, id_=1):
    return server.handle({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


def call(server, name, args):
    res = rpc(server, "tools/call", {"name": name, "arguments": args})["result"]
    return json.loads(res["content"][0]["text"]) if not res["isError"] else res["content"][0]["text"]


def test_handshake_and_tool_listing(server):
    assert rpc(server, "initialize")["result"]["serverInfo"]["name"] == "memoraos"
    assert {t["name"] for t in rpc(server, "tools/list")["result"]["tools"]} == {t["name"] for t in TOOLS}
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(server, "nope")["error"]["code"] == -32601


def test_tools_round_trip(server):
    call(server, "memora_remember", {"text": "Parth's salary is ₹32 LPA."})
    out = call(server, "memora_recall", {"query": "What is Parth's salary?"})
    assert out["answer"] == "₹32 LPA" and out["evidence"]
    assert call(server, "memora_explain", {"recall_id": out["recall_id"]})["strategy"] == "exact"
    mid = out["evidence"][0]["memory_id"]
    assert call(server, "memora_correct", {"memory_id": mid, "new_content": "Parth's salary is ₹33 LPA."})["version"] == 2
    assert call(server, "memora_history", {"subject": "Parth", "predicate": "salary"})["timeline"]
    assert call(server, "memora_forget", {"memory_id": mid}) == {"deleted": 1}


def test_errors_are_tool_errors_and_user_cannot_be_overridden(server, mem):
    assert "error" in call(server, "memora_recall", {})  # missing argument
    assert "error" in call(server, "memora_forget", {"memory_id": "mem_nope"})
    mem.remember("Secret of someone else.", user_id="other")
    call(server, "memora_remember", {"text": "I like tea.", "user_id": "other"})  # extra argument is ignored
    assert [m.original_content for m in mem.list_memories(user_id="other")] == ["Secret of someone else."]
    assert rpc(server, "tools/call", {"name": "shell_exec", "arguments": {}})["error"]["code"] == -32602


def test_stdio_loop():
    from memoraos import MemoryOS

    m = MemoryOS.in_memory()
    s = McpServer(m, "u")
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), "{not json", json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})]
    out = io.StringIO()
    s.serve(io.StringIO("\n".join(lines) + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert replies[0]["result"] == {} and replies[1]["error"]["code"] == -32700 and len(replies) == 2
