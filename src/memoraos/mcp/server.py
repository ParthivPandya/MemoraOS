"""MCP (Model Context Protocol) stdio server. Dependency-free JSON-RPC 2.0 over newline-delimited stdin/stdout.

Exposes memory tools to MCP clients. Retrieved memory is returned as data; tool results never contain
instructions for the host, and the user id is fixed by configuration, not by the model.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, TextIO

from .. import __version__
from ..engine import MemoryOS, NotFoundError, PermissionDenied

PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "memora_remember",
        "description": "Store a piece of information in long-term memory.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "effective_at": {"type": "string", "description": "ISO date the information became true"}}, "required": ["text"]},
    },
    {
        "name": "memora_recall",
        "description": "Answer a question from memory with evidence. Returns insufficient_evidence instead of guessing.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "as_of": {"type": "string", "description": "ISO timestamp for time-travel recall"}, "top_k": {"type": "integer"}}, "required": ["query"]},
    },
    {
        "name": "memora_correct",
        "description": "Replace the content of a memory with a corrected version (history is kept).",
        "inputSchema": {"type": "object", "properties": {"memory_id": {"type": "string"}, "new_content": {"type": "string"}, "reason": {"type": "string"}}, "required": ["memory_id", "new_content"]},
    },
    {
        "name": "memora_forget",
        "description": "Permanently delete a memory.",
        "inputSchema": {"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]},
    },
    {
        "name": "memora_history",
        "description": "Value timeline for a subject and predicate (for example subject 'Parth', predicate 'salary').",
        "inputSchema": {"type": "object", "properties": {"subject": {"type": "string"}, "predicate": {"type": "string"}}, "required": ["subject", "predicate"]},
    },
    {
        "name": "memora_explain",
        "description": "Explain how a previous recall was answered (strategy, attempts, evidence).",
        "inputSchema": {"type": "object", "properties": {"recall_id": {"type": "string"}}, "required": ["recall_id"]},
    },
]


class McpServer:
    def __init__(self, engine: MemoryOS, user_id: str, tenant_id: str = "default"):
        self.engine, self.user_id, self.tenant_id = engine, user_id, tenant_id

    def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        kw = {"user_id": self.user_id, "tenant_id": self.tenant_id}
        e = self.engine
        if name == "memora_remember":
            return e.remember(str(args["text"]), effective_at=args.get("effective_at"), **kw).model_dump()
        if name == "memora_recall":
            r = e.recall(str(args["query"]), as_of=args.get("as_of"), top_k=args.get("top_k"), **kw)
            return {"answer": r.answer, "status": r.status, "strategy": r.strategy, "recall_id": r.recall_id, "evidence": [ev.model_dump() for ev in r.evidence], "contradictions": [c.model_dump() for c in r.contradictions], "flags": r.flags}
        if name == "memora_correct":
            return e.correct(str(args["memory_id"]), str(args["new_content"]), reason=args.get("reason"), **kw).model_dump()
        if name == "memora_forget":
            return {"deleted": e.forget(str(args["memory_id"]), **kw)}
        if name == "memora_history":
            return e.history(subject=str(args["subject"]), predicate=str(args["predicate"]), **kw)
        if name == "memora_explain":
            return e.explain(str(args["recall_id"]), **kw)
        raise KeyError(name)

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notification
            return None

        def ok(result: Any) -> dict:
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        def err(code: int, text: str) -> dict:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

        if method == "initialize":
            return ok({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": {"name": "memoraos", "version": __version__}})
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            params = msg.get("params") or {}
            name, args = params.get("name"), params.get("arguments") or {}
            if name not in {t["name"] for t in TOOLS}:
                return err(-32602, f"unknown tool {name}")
            try:
                result = self.call_tool(name, args)
                return ok({"content": [{"type": "text", "text": json.dumps(result, default=str)}], "isError": False})
            except (KeyError, ValueError, NotFoundError, PermissionDenied) as exc:
                return ok({"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
        return err(-32601, f"method not found: {method}")

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
                stdout.flush()
                continue
            resp = self.handle(msg)
            if resp is not None:
                stdout.write(json.dumps(resp) + "\n")
                stdout.flush()


def main() -> None:
    user = os.environ.get("MEMORAOS_USER_ID")
    if not user:
        sys.stderr.write("MEMORAOS_USER_ID must be set (the MCP server acts as exactly one user).\n")
        raise SystemExit(2)
    engine = MemoryOS.local(os.environ.get("MEMORAOS_DATA_DIR") or None)
    McpServer(engine, user, os.environ.get("MEMORAOS_TENANT_ID", "default")).serve()


if __name__ == "__main__":
    main()
