"""The chat proxy against a fake upstream (no real OpenAI or Anthropic server is contacted)."""

from __future__ import annotations

import json

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from memoraos.proxy import create_proxy_app, reply_text, sse_text  # noqa: E402

U = "user_001"
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0"


class Upstream:
    def __init__(self, reply: dict | None = None, sse: list[str] | None = None, fail: bool = False):
        self.requests: list[httpx.Request] = []
        self.reply, self.sse, self.fail = reply or {"ok": True}, sse, fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("down", request=request)
        if self.sse is not None:
            data = "".join(f"data: {s}\n\n" for s in self.sse).encode()
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=httpx.ByteStream(data))
        return httpx.Response(200, json=self.reply)

    @property
    def body(self) -> dict:
        return json.loads(self.requests[-1].content)


def client(mem, up: Upstream, target: str = "https://up.example/v1", **kw):
    app = create_proxy_app(mem, target, user_id=U, transport=httpx.MockTransport(up), **kw)
    return TestClient(app)


def stored(mem, origin: str) -> list[str]:
    rows = mem.db.query("SELECT m.original_content AS c FROM memories m JOIN sources s ON s.id=m.source_id WHERE s.origin=?", (origin,))
    return [r["c"] for r in rows]


def chat(text: str) -> dict:
    return {"model": "m", "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": text}]}


def test_openai_request_gets_cited_context_and_original_question_is_kept(mem):
    mem.remember("The deploy region is eu-west-1.", user_id=U)
    up = Upstream()
    with client(mem, up) as c:
        r = c.post("/v1/chat/completions", json=chat("What is the deploy region?"), headers={"authorization": "Bearer k"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    sent = up.body["messages"][-1]["content"]
    assert sent.startswith("<memoraos_context>") and "eu-west-1" in sent and sent.endswith("What is the deploy region?")
    assert up.body["messages"][0]["content"] == "be brief"
    assert str(up.requests[-1].url) == "https://up.example/v1/chat/completions"
    assert up.requests[-1].headers["authorization"] == "Bearer k"
    assert int(r.headers["x-memoraos-evidence"]) >= 1


def test_unsupported_question_adds_no_context(mem):
    mem.remember("The deploy region is eu-west-1.", user_id=U)
    up = Upstream()
    with client(mem, up) as c:
        r = c.post("/v1/chat/completions", json=chat("What is the CEO's shoe size?"))
    assert up.body["messages"][-1]["content"] == "What is the CEO's shoe size?"
    assert r.headers["x-memoraos-evidence"] == "0" and r.headers["x-memoraos-warnings"] == "0"


def test_failed_attempt_is_injected_as_a_warning(mem):
    mem.remember_outcome("upgrade the requests library to 3.0", "failed", reason="breaks the retry adapter", user_id=U)
    up = Upstream()
    with client(mem, up) as c:
        r = c.post("/v1/chat/completions", json=chat("Should I upgrade the requests library?"))
    sent = up.body["messages"][-1]["content"]
    assert "failed" in sent and "breaks the retry adapter" in sent and r.headers["x-memoraos-warnings"] == "1"


def test_anthropic_blocks_and_path(mem):
    mem.remember("The deploy region is eu-west-1.", user_id=U)
    up = Upstream({"content": [{"type": "text", "text": "ok"}]})
    body = {"model": "m", "system": "s", "messages": [{"role": "user", "content": [{"type": "text", "text": "What is the deploy region?"}]}]}
    with client(mem, up, "https://api.example.com") as c:
        c.post("/v1/messages", json=body)
    blocks = up.body["messages"][-1]["content"]
    assert blocks[0]["text"].startswith("<memoraos_context>") and blocks[-1]["text"] == "What is the deploy region?"
    assert up.body["system"] == "s" and str(up.requests[-1].url) == "https://api.example.com/v1/messages"


def test_secret_is_redacted_before_it_leaves_and_never_stored(mem):
    up = Upstream()
    with client(mem, up) as c:
        r = c.post("/v1/chat/completions", json=chat(f"my key is {KEY}, what should I name the bucket?"))
    assert KEY not in json.dumps(up.body) and r.headers["x-memoraos-redactions"] == "1"
    assert all(KEY not in s for s in stored(mem, "proxy-openai"))
    logged = [r["query"] for r in mem.db.query("SELECT query FROM retrieval_log")]
    assert logged and all(KEY not in q for q in logged)


def test_user_message_is_stored_as_hypothesis_and_capture_none_stores_nothing(mem):
    with client(mem, Upstream()) as c:
        c.post("/v1/chat/completions", json=chat("We migrated the billing service to Postgres."))
    assert stored(mem, "proxy-openai") == ["user: We migrated the billing service to Postgres."]
    rec = mem.db.one("SELECT s.verification AS v FROM sources s WHERE s.origin='proxy-openai'")
    assert rec["v"] == "hypothesis"
    with client(mem, Upstream(), capture="none") as c:
        c.post("/v1/chat/completions", json=chat("Another unrelated sentence about lunch."))
    assert len(stored(mem, "proxy-openai")) == 1


def test_no_inject_forwards_the_question_unchanged(mem):
    mem.remember("The deploy region is eu-west-1.", user_id=U)
    up = Upstream()
    with client(mem, up, inject=False) as c:
        c.post("/v1/chat/completions", json=chat("What is the deploy region?"))
    assert up.body["messages"][-1]["content"] == "What is the deploy region?"


def test_sse_stream_is_passed_through_and_reply_stored_only_with_capture_both(mem):
    events = [json.dumps({"choices": [{"delta": {"content": part}}]}) for part in ("Eu", "-west-1")] + ["[DONE]"]
    with client(mem, Upstream(sse=events), capture="both") as c:
        r = c.post("/v1/chat/completions", json={**chat("Where do we deploy?"), "stream": True})
    assert r.text.count("data:") == 3 and "[DONE]" in r.text
    assert "assistant: Eu-west-1" in stored(mem, "proxy-openai")
    with client(mem, Upstream(sse=events), capture="user") as c:
        c.post("/v1/chat/completions", json={**chat("Where else do we deploy?"), "stream": True})
    assert len([s for s in stored(mem, "proxy-openai") if s.startswith("assistant:")]) == 1


def test_non_stream_reply_text_helpers():
    assert reply_text("openai", {"choices": [{"message": {"content": "hi"}}]}) == "hi"
    assert reply_text("anthropic", {"content": [{"type": "text", "text": "a"}, {"type": "tool_use"}]}) == "a"
    assert sse_text("anthropic", b'data: {"type":"content_block_delta","delta":{"text":"x"}}') == "x"
    assert sse_text("openai", b"data: [DONE]") == "" and sse_text("openai", b": ping") == ""


def test_recall_failure_does_not_break_the_call(mem, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("memory is down")

    monkeypatch.setattr(mem, "recall", boom)
    monkeypatch.setattr(mem, "outcome_warnings", boom)
    up = Upstream()
    with client(mem, up) as c:
        r = c.post("/v1/chat/completions", json=chat("What is the deploy region?"))
    assert r.status_code == 200 and up.body["messages"][-1]["content"] == "What is the deploy region?"


def test_other_paths_pass_through_and_upstream_errors_become_502(mem):
    up = Upstream({"data": []})
    with client(mem, up) as c:
        r = c.get("/v1/models?limit=2")
    assert r.json() == {"data": []} and str(up.requests[-1].url) == "https://up.example/v1/models?limit=2"
    assert "x-memoraos-evidence" not in r.headers
    with client(mem, Upstream(fail=True)) as c:
        r = c.post("/v1/chat/completions", json=chat("hello there"))
    assert r.status_code == 502 and "upstream unreachable" in r.json()["error"]["message"]


def test_invalid_capture_mode_is_rejected(mem):
    with pytest.raises(ValueError):
        create_proxy_app(mem, "https://x", user_id=U, capture="everything")
