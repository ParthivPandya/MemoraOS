# Roadmap

Legend: ✅ done · 🧪 experimental · ⏳ planned. Nothing marked planned is implemented.

## Done (v0.1)

✅ SQLite storage, migrations, backup · ✅ BM25 + vector + RRF · ✅ adaptive router with fallbacks · ✅ bitemporal facts, contradictions, time travel, audit chain · ✅ consolidation with rollback · ✅ multi-tenant isolation · ✅ REST API, Python client, TypeScript SDK, MCP server · ✅ dashboard · ✅ benchmark lab · 🧪 latent-memory interface + CPU baseline

## Next (highest value first)

1. ⏳ **Fix the paraphrase weakness**: optional LLM/NER-assisted fact extraction behind `EntityExtractor`, evaluated on `paraphrase_robustness` before and after; add predicate synonym learning.
2. ⏳ **Standard benchmarks**: LoCoMo and LongMemEval adapters (license permitting) with a fixed, disclosed judge; neural-embedder runs (Ollama `nomic-embed-text`, Qwen embeddings) alongside the hashing embedder.
3. ⏳ **Executable baselines**: real Mem0 / Graphiti / Hindsight adapters that run when installed (with local Ollama), reported only from actual runs.
4. ⏳ **Scale**: ANN vector adapter (FAISS / sqlite-vec), incremental graph, measured 10⁵–10⁶ memory runs.
5. ⏳ **Encryption at rest** (SQLCipher adapter) and key rotation.
6. ⏳ **Contextual bandit** router tuning (only with a labelled-feedback dataset and the existing accuracy guard).
7. 🧪→⏳ **Learned latent memory**: Memorilla checkpoint adapter on a GPU host, information-preservation evaluation ([LATENT_MEMORY.md](LATENT_MEMORY.md)).
8. ⏳ Storage adapters: PostgreSQL, external graph DB, object storage for documents.
9. ⏳ Multimodal ingestion (OCR/captioning providers).
10. ⏳ Reranker integration in the retrieval path (interface exists; default is lexical coverage).
