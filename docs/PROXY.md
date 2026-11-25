# Memory proxy (`memoraos proxy`)

A small local HTTP proxy that sits between an OpenAI- or Anthropic-compatible client and its upstream API. Before a request is forwarded it adds memory to the prompt; after that it stores what the user said. The client only needs a different base URL.

```bash
memoraos --data-dir ~/.memoraos proxy --target https://api.openai.com/v1 --user me --port 8080
# then point the client at it:  OPENAI_BASE_URL=http://127.0.0.1:8080/v1
```

For Anthropic: `--target https://api.anthropic.com` and `ANTHROPIC_BASE_URL=http://127.0.0.1:8080`. Your own API key is forwarded unchanged; the proxy neither stores nor logs it.

## What it does to a request

Handled paths: OpenAI `POST /chat/completions` (under whatever prefix the target has) and Anthropic `POST /v1/messages`. Everything else is passed through untouched.

1. Takes the **last user message** and redacts secrets in it with the normal ingestion firewall (`[REDACTED:api_key]` and so on). Earlier messages are not scanned.
2. Looks the redacted text up: `outcome_warnings` first, then `recall`.
3. If there are matching recorded failures, or the recall is `answered` / `conflict` with evidence, it appends a `<memoraos_context>` block to that user message. Retrieved text is neutralised and labelled as untrusted data. If the recall is `insufficient_evidence`, nothing is added.
4. Forwards the request. Streaming (SSE) responses are passed through as they arrive.
5. Stores the user's text as a `hypothesis` memory (default `--capture user`). `--capture both` also stores the assistant's reply (streamed replies are reassembled from the SSE text); `--capture none` stores nothing; `--no-inject` captures without adding memory; `--no-redact` disables redaction.

Response headers show what happened: `x-memoraos-evidence`, `x-memoraos-warnings`, `x-memoraos-redactions`.

A memory failure never breaks the call (the request is forwarded as it was). An upstream error is returned as HTTP 502.

## Safety

- The proxy has no authentication, so it binds to loopback and **refuses a non-loopback `--host`** unless you pass `--allow-remote`.
- Captured text is stored as `hypothesis`, never as verified fact.

## Limitations (read these)

- **Tested only against a local fake upstream** (`tests/integration/test_proxy.py`, plus one real uvicorn process in front of a fake upstream). It has not been run against real OpenAI or Anthropic endpoints, nor with Aider, OpenWebUI, LibreChat, LangChain or CrewAI. Other client features (tool calls, images, other endpoints) are forwarded but not otherwise handled.
- **Injection only fires when the question is answerable from memory.** In a manual check, a short direct question got three evidence items injected, while the same question wrapped in a chatty request ("Help me with this: when did we add ...") got none because the answerability gate refused. This was observed on one store, not measured.
- Only the latest user message is used as the query and only that message is redacted.
- The assistant's reply is not stored unless you pass `--capture both`.
- Nothing here changes what the upstream model does with the context; it may ignore it.
