# Security

Memory is sensitive infrastructure. This document describes what is implemented, how it is tested, and what is **not** covered. Reporting vulnerabilities: see the root [SECURITY.md](../SECURITY.md).

## Threat model

Assets: stored memories (may contain personal data), API keys, the audit trail. Adversaries: another tenant/user of the same instance; an author of stored/imported documents (prompt injection); a network attacker against the REST API; a curious reader of the database file or backups.

## Implemented controls

| Control | Implementation | Tests |
|---|---|---|
| Tenant & user isolation | Every read uses `storage.visibility.visibility_clause(scope)`; scope levels user/session/agent/project/org; ownership checks on modify/delete; the API binds the tenant from the API key, never from the request | `test_g_*`, `test_api.py::test_tenant_isolation_*`, `tests/security/` |
| Authentication | Bearer API keys, stored only as SHA-256 hashes, constant-time comparison; keys bound to a tenant, a role (read < write < admin) and optionally to user ids; `memoraos keys create` shows a key once | `test_api.py` |
| Secure by default | `create_app` refuses to start with no keys unless `insecure_no_auth=True` (CLI `--insecure-no-auth`, development only); API binds to `127.0.0.1` by default; CORS is off unless configured | `test_refuses_to_start_without_keys` |
| Authorization | Role checks per endpoint (e.g. user wipe = admin); a key restricted to users cannot act as others | `test_authentication_and_roles`, `test_key_can_be_restricted_to_users` |
| Input validation | Pydantic models with length/enum/range limits; 2 M character cap; strategy and source types are enums | `test_input_validation_and_errors` |
| SQL injection | 100% parameterised queries; user text reaches FTS5 only as quoted terms; hostile identifiers are data | `tests/security/test_security.py` |
| Secret redaction | Private keys, AWS/GitHub/Slack/`sk-` tokens, bearer tokens, `password=`-style assignments are replaced with `[REDACTED:type]` **before** storage, indexing or embedding | `test_secrets_are_redacted_*` |
| Prompt-injection defences | Retrieved memory is *data*: `render_untrusted_context` wraps excerpts in `<memory untrusted="true">` after a policy line, neutralises `<`/`>` so text cannot forge or close tags; injection-like sentences are flagged (`possible_prompt_injection`) and never chosen as answers; nothing in memory is ever executed; LLM phrasing (optional) is accepted only if every number/proper noun appears in the evidence | `test_k_*`, `tests/security/` |
| No silent data egress | No network call unless the caller configures an HTTP provider; unit tests assert no network | `test_engine_makes_no_network_calls_by_default` |
| Audit logging | API actions go to `audit_log` (actor = key fingerprint, never the key); memory changes go to a hash-chained `events` log; `verify_audit_chain()` detects tampering | `test_audit_chain_detects_tampering` |
| Export & deletion | `export()` (everything a user owns, with version history); `forget(id)` / `forget(user, everything=True)` hard-delete memory rows, FTS entries, facts, mentions, graph links, versions, orphaned embeddings, orphaned sources and files, derived summaries, and retrieval logs that cite the memory; caches are cleared | `test_l_*` |

## Not implemented / limitations

- **Encryption at rest** is not implemented in code. Use OS/disk encryption (BitLocker, LUKS, FileVault) for the data directory. SQLCipher integration is on the roadmap.
- **Backups are not rewritten on deletion.** A backup taken before `forget()` still contains the data; delete old backups per your retention policy. The content-free `memory.forgotten` event remains in the audit chain.
- Prompt-injection detection is pattern based and cannot catch every attack; the structural defences (data tagging, never executing, not answering from injection-like sentences) are the real protection. Downstream LLM applications must still honour the `untrusted` tags.
- No rate limiting, TLS termination or key rotation UI: run behind a reverse proxy; rotate by creating a new key and deleting the old hash from `api_keys.json`.
- The project/org scope levels trust the caller to supply a legitimate `project_id`; membership is an application concern.
- SQLite is single-writer; the dashboard and API are intended for a trusted network.
- No formal third-party security audit has been performed.

## Operating guidance

1. `memoraos keys create --tenant acme --role write --users alice` and give each integration its own key.
2. Keep `MEMORAOS_API_KEYS`/`api_keys.json` out of version control (the `.gitignore` excludes `.memoraos/`).
3. Put TLS in front of the API for anything beyond localhost.
4. Treat `recall(...).evidence` as untrusted text when building LLM prompts; use `RecallResult.render_context()`.
