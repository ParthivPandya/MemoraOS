# ADR-0004: Embedding provider v2 and a model registry

**Status:** Accepted · 2026-11-17

**Context.** v0.1 records only `model` and `dim` per vector. The spec requires provider, model version, dimension, normalization, timestamp, content hash and status, and forbids mixing incompatible vectors. Providers are also expected to expose health and model information.

**Decision.**
- `EmbeddingProvider` becomes a base class with `embed_text`, `embed_batch`, `get_model_info`, `get_embedding_dimension`, `health_check`. `embed()` remains as an alias of `embed_batch` so v0.1 callers and tests work. Objects implementing only the v0.1 protocol are wrapped by `adapt_embedder()`.
- Add `embedding_models` (registry) and extra `embeddings` columns. A model name registered with one dimension cannot be reused with another (`EmbeddingModelMismatch`).
- Vector search only reads vectors of the active model; a dimension check guards every matrix build.
- `MemoryOS.reembed()` re-embeds memories whose vector belongs to another model, in batches, and can retire old vectors. `rebuild_index()` clears caches.
- `SentenceTransformerEmbedder` is an optional adapter with a lazy import.

**Consequences.** Switching providers is safe and observable; stale vectors are never searched. Real neural embedders remain unbenchmarked until run on a machine with the model installed; this is stated wherever relevant.
