# Performance

Rule for this repository: **no performance claim without a measurement** that can be reproduced. Numbers below come from `python -m benchmarks.run` (see `benchmarks/reports/REPORT.md` for full tables and hardware: Windows 11, 8 logical CPUs, 7.7 GB RAM, Python 3.14.3).

## Measured (small synthetic workloads; indicative only)

| Metric | MemoraOS | Plain hybrid RAG baseline |
|---|---|---|
| Query latency p50 (median over scenarios) | ≈ 6.5 ms | ≈ 2.2 ms |
| Update (ingest) cost | ≈ 13.7 ms / event | ≈ 2.3 ms / event |
| Evidence tokens returned per question | ≈ 29 | ≈ 78 |
| Storage ÷ raw text (tiny texts) | ≈ 351× | ≈ 59× |
| Restart (reopen) | ≈ 0.07 s | ≈ 0.03 s (rebuild index from raw docs) |

MemoraOS pays more per query and per write (routing, fact timelines, FTS, version and audit rows) in exchange for the accuracy results in the benchmark. It returns fewer evidence tokens because answers are resolved facts, not extra passages. These token figures describe *evidence returned*, not LLM cost; no LLM is used in the benchmark.

`tests/regression/test_regression.py` enforces coarse budgets (300 memories ingested < 60 s, per-query < 250 ms) to catch order-of-magnitude regressions.

## Optimisations implemented

| Feature | Where |
|---|---|
| Embedding cache keyed by content hash and model (never re-embed identical text; deleted with its last memory) | `Store.embed_texts` |
| Batch embedding per `remember` call | `engine.remember` |
| Incremental re-indexing when the embedder changes (backfill only missing vectors) | `VectorIndex.ensure_embeddings` |
| Cached vector matrix per scope, invalidated by the event sequence number | `VectorIndex._matrix` |
| Query cache (LRU, key includes scope, query, `as_of`, store version, embedder) — invalidated by any write | `Recaller.recall` |
| Graph cache per store version | `Recaller._graph` |
| SQLite WAL, covering indexes on scope/hash/slot/entity, FTS5 BM25 | `storage/db.py` |
| Lazy optional components (FastAPI, latent, providers imported on use) | package layout |
| Avoidance of LLM calls: routing, answers, consolidation and reflection are deterministic | by design |
| Configurable limits (`candidate_pool`, `default_top_k`, `max_graph_hops`, `query_cache_size`) | `Settings` |
| Background consolidation (thread, incremental watermark) | `ConsolidationScheduler` |

Statistics are exposed by `MemoryOS.stats()` / `GET /v1/stats`: counts, recall latency p50/p95, mean evidence tokens, unsupported rate, cache hits/misses, provider token/cost usage, storage bytes.

## Known scaling limits

- Vector search is exact brute force over an in-memory matrix: fine to roughly 10⁵ memories per scope; beyond that use an ANN adapter (roadmap).
- `build_graph` and consolidation are O(n) / O(n²) in memories of a scope (`MAX_MEMORIES = 5000` per consolidation run).
- Single SQLite writer.
- Not yet measured: large corpora (≥ 10⁵ memories), concurrent clients, neural-embedder latency.
