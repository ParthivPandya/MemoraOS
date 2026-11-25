"""A local proxy for OpenAI- and Anthropic-style chat APIs that adds MemoraOS memory to any client.

Point a client's base URL at the proxy. For every chat request the proxy

1. optionally redacts obvious secrets from the latest user message (the same patterns as ``remember``),
2. looks the message up in MemoraOS and, when something is stored that supports it, prepends cited evidence and any
   recorded failed attempts (see ``context.py``) to that message as delimited, untrusted data,
3. forwards the request to the real API untouched otherwise (any other path is passed through unchanged), and
4. stores the user message, and optionally the reply, as ``hypothesis`` memories (never as trusted facts).

Memory problems never break the call: if recall or storage fails, the request is forwarded as it came in. The proxy
has no authentication of its own, so it should only listen on a loopback address.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from . import __version__
from .context import MemoryContext, build_context
from .engine import MemoryOS
from .security import redact_secrets

CAPTURE_MODES = ("none", "user", "both")
_CHAT = {"chat/completions": "openai", "messages": "anthropic"}
_SKIP_REQUEST = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "accept-encoding", "upgrade", "te", "trailer"}
_SKIP_RESPONSE = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}
MAX_STORED_CHARS = 4000


def _blocks(content: Any) -> list[dict]:
    return [b for b in content if isinstance(b, dict) and b.get("type") == "text"] if isinstance(content, list) else []


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(str(b.get("text", "")) for b in _blocks(content))


def _last_user_text_index(messages: Any) -> int | None:
    """Index of the last user message that carries text (tool-result-only turns have none)."""
    if not isinstance(messages, list):
        return None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, dict) and m.get("role") == "user":
            return i if _text(m.get("content")).strip() else None
    return None


def rewrite_user_message(message: dict, context: str, redact: bool) -> int:
    """Redact the message text and prepend ``context``; returns the number of redactions."""
    redactions = 0
    content = message.get("content")
    if isinstance(content, str):
        if redact:
            content, redactions = redact_secrets(content)
        message["content"] = f"{context}\n\n{content}" if context else content
    elif isinstance(content, list):
        for block in _blocks(content):
            if redact and isinstance(block.get("text"), str):
                block["text"], n = redact_secrets(block["text"])
                redactions += n
        if context:
            content.insert(0, {"type": "text", "text": context})
    return redactions


def reply_text(kind: str, data: Any) -> str:
    """Assistant text of a non-streaming response body."""
    if not isinstance(data, dict):
        return ""
    if kind == "anthropic":
        return _text(data.get("content"))
    choices = data.get("choices") or []
    msg = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
    return _text(msg.get("content")) if isinstance(msg, dict) else ""


def sse_text(kind: str, line: bytes) -> str:
    """Text carried by one server-sent-events line of a streamed response ('' for anything else)."""
    if not line.startswith(b"data:"):
        return ""
    try:
        d = json.loads(line[5:].strip() or b"null")
    except ValueError:
        return ""
    if not isinstance(d, dict):
        return ""
    if kind == "anthropic":
        delta = d.get("delta") or {}
        return str(delta.get("text", "")) if d.get("type") == "content_block_delta" and isinstance(delta, dict) else ""
    choices = d.get("choices") or []
    delta = choices[0].get("delta") if choices and isinstance(choices[0], dict) else None
    return delta.get("content") or "" if isinstance(delta, dict) and isinstance(delta.get("content"), str) else ""


def create_proxy_app(
    engine: MemoryOS, target: str, *, user_id: str, tenant_id: str = "default", inject: bool = True, capture: str = "user",
    redact: bool = True, max_evidence: int = 4, timeout: float = 300.0, transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    if capture not in CAPTURE_MODES:
        raise ValueError(f"capture must be one of {', '.join(CAPTURE_MODES)}")
    base = target.rstrip("/")
    client = httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()

    app = FastAPI(title="MemoraOS proxy", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def upstream_url(path: str, query: str) -> str:
        if base.endswith("/v1") and path.startswith("v1/"):
            path = path[3:]
        return f"{base}/{path}" + (f"?{query}" if query else "")

    def remember(text: str, role: str, kind: str) -> None:
        try:
            engine.remember(
                f"{role}: {text.strip()[:MAX_STORED_CHARS]}", user_id=user_id, tenant_id=tenant_id, source_type="conversation",
                verification="hypothesis", extract=False, origin=f"proxy-{kind}", metadata={"role": role},
            )
        except Exception:  # noqa: BLE001 - storing must never fail the call
            pass

    def prepare(body: dict, kind: str) -> tuple[bytes, dict[str, str], str]:
        """Rewrite the request body; returns (body, response headers, the user text that was looked up)."""
        headers = {"x-memoraos-evidence": "0", "x-memoraos-warnings": "0", "x-memoraos-redactions": "0"}
        idx = _last_user_text_index(body.get("messages"))
        if idx is None:
            return json.dumps(body).encode(), headers, ""
        message = body["messages"][idx]
        query = _text(message.get("content")).strip()
        ctx = MemoryContext()
        if inject:
            try:
                ctx = build_context(engine, query, user_id=user_id, tenant_id=tenant_id, max_evidence=max_evidence)
            except Exception:  # noqa: BLE001 - recall problems must not break the call
                ctx = MemoryContext()
        redactions = rewrite_user_message(message, ctx.text, redact)
        if capture != "none":
            remember(query, "user", kind)
        headers.update({"x-memoraos-evidence": str(ctx.evidence), "x-memoraos-warnings": str(ctx.warnings), "x-memoraos-redactions": str(redactions)})
        return json.dumps(body).encode(), headers, query

    async def stream_back(upstream: httpx.Response, kind: str) -> AsyncIterator[bytes]:
        pieces: list[str] = []
        buf = b""
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
                if capture == "both":
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    pieces += [sse_text(kind, ln.strip()) for ln in lines]
        finally:
            await upstream.aclose()
            if capture == "both" and "".join(pieces).strip():
                await run_in_threadpool(remember, "".join(pieces), "assistant", kind)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def forward(path: str, request: Request) -> Response:
        raw = await request.body()
        kind = _CHAT.get(path[3:] if path.startswith("v1/") else path)
        out_headers: dict[str, str] = {}
        content = raw
        if request.method == "POST" and kind:
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            if isinstance(body, dict):
                content, out_headers, _ = await run_in_threadpool(prepare, body, kind)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_REQUEST}
        headers["accept-encoding"] = "identity"
        req = client.build_request(request.method, upstream_url(path, request.url.query), headers=headers, content=content)
        try:
            upstream = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            return Response(json.dumps({"error": {"message": f"upstream unreachable: {type(exc).__name__}", "type": "memoraos_proxy"}}), status_code=502, media_type="application/json")
        resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _SKIP_RESPONSE} | out_headers
        if kind and upstream.headers.get("content-type", "").startswith("text/event-stream"):
            return StreamingResponse(stream_back(upstream, kind), status_code=upstream.status_code, headers=resp_headers)
        data = await upstream.aread()
        await upstream.aclose()
        if kind and capture == "both" and upstream.status_code < 300:
            try:
                text = reply_text(kind, json.loads(data))
            except ValueError:
                text = ""
            if text.strip():
                await run_in_threadpool(remember, text, "assistant", kind)
        return Response(data, status_code=upstream.status_code, headers=resp_headers)

    return app
