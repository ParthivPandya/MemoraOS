# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [0.1.0] - 2026-11-17

### Added
- SQLite-first memory engine: versioned migrations, WAL, FTS5 BM25, cached embeddings, online backup.
- Ingestion: text, conversations, structured JSON, documents; chunking; secret redaction; rule-based fact/entity/date extraction; duplicate detection.
- Retrieval: BM25, vector, RRF hybrid, graph (multi-hop), episodic, procedural, temporal, multistage; optional latent strategy (experimental).
- Adaptive router with cost-aware selection, fallbacks, optional model classifier, and accuracy-guarded feedback learning (off by default).
- Truth engine: bitemporal fact timelines, contradiction/version-change analysis, source reliability, evidence-supported answers, abstention.
- Time travel: version history, as-of recall, snapshots, change log, hash-chained event log.
- Consolidation: near-duplicate links, conservative alias merges, derived summaries, importance, incremental/dry-run/scheduled modes, rollback.
- Multi-tenant isolation with user/session/agent/project/org scopes; export; hard delete.
- REST API (API-key auth, roles, audit log), Python client, TypeScript SDK, MCP stdio server, CLI.
- Next.js dashboard backed by live API data.
- Memory Benchmark Lab with 15 scenarios, baselines, ablation, bootstrap CIs, deterministic digest.
- Provider abstraction: Ollama and OpenAI-compatible adapters with retries, timeouts, fallbacks, usage tracking.

### Known limitations
See README "Limitations" and docs/IMPLEMENTATION_STATUS.md.
