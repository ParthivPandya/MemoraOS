# Roadmap

Legend: ✅ done · 🧪 experimental · ⏳ planned. Nothing marked planned is implemented.

## Done (v0.1)

✅ SQLite storage, migrations, backup · ✅ BM25 + vector + RRF · ✅ adaptive router with fallbacks · ✅ bitemporal facts, contradictions, time travel, audit chain · ✅ consolidation with rollback · ✅ multi-tenant isolation · ✅ REST API, Python client, TypeScript SDK, MCP server · ✅ dashboard · ✅ benchmark lab · 🧪 latent-memory interface + CPU baseline

## Next (highest value first)

1. ⏳ **Fix the paraphrase weakness**: optional LLM/NER-assisted fact extraction behind `EntityExtractor`, evaluated on `paraphrase_robustness` before and after; add predicate synonym learning.
2. 🧪 **Standard benchmarks**: LoCoMo and LongMemEval retrieval-only adapters now exist (`benchmarks/public.py`); the answer-accuracy judge is still ⏳ and needs an LLM. Neural-embedder runs on the public sets are ⏳.
3. ⏳ **Executable baselines**: real Mem0 / Graphiti / Hindsight adapters that run when installed (with local Ollama), reported only from actual runs.
4. 🧪 **Scale**: opt-in IVF vector index measured on real text (recall 0.52-0.93, so exact search stays the default); FAISS / sqlite-vec, incremental graph and 10⁶-memory runs are ⏳.
5. ✅ **Encryption at rest** (opt-in AES-256-GCM, see [SECURITY.md](SECURITY.md)); key rotation is ⏳.
6. ⏳ **Contextual bandit** router tuning (only with a labelled-feedback dataset and the existing accuracy guard).
7. 🧪→⏳ **Learned latent memory**: Memorilla checkpoint adapter on a GPU host, information-preservation evaluation ([LATENT_MEMORY.md](LATENT_MEMORY.md)).
8. ⏳ Storage adapters: PostgreSQL, external graph DB, object storage for documents.
9. ⏳ Multimodal ingestion (OCR/captioning providers).
10. ⏳ Reranker integration in the retrieval path (interface exists; default is lexical coverage).
