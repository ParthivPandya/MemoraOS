# Latent Semantic Memory (Experimental)

> **Status: experimental.** MemoraOS does **not** reproduce Stanford's Memorilla. Ordinary embedding search is not equivalent to it and is not presented as such.

## What Memorilla is (verified from the paper and repository)

Learned latent memory: a frozen encoder embeds documents once; a **trained** memory module cross-attends over the embedding store and emits a fixed number of **query-conditioned soft tokens** in a frozen decoder LLM's embedding space (arXiv 2610.21375; <https://github.com/snap-stanford/memorilla>). It needs three training stages, a GPU, and a specific decoder. See [RESEARCH_AND_COMPETITIVE_ANALYSIS.md](RESEARCH_AND_COMPETITIVE_ANALYSIS.md).

## What this repository provides

| Piece | Where | Status |
|---|---|---|
| `LatentMemoryBackend` interface (`fit`, `readout`, `retrieve`, `stats`) | `memoraos.latent.base` | Stable contract |
| `LatentMemoryModel` interface (document encoder + `memory_tokens(query)`) | `memoraos.latent.base` | Contract only; **no implementation** |
| `SlotAttentionMemory` | `memoraos.latent.slots` | CPU baseline: k-means slots + softmax-attention readout. **Not trained end to end**, not a Memorilla reproduction |
| `LatentIndex` / `MemoryOS.enable_latent()` | `memoraos.latent.index` | Exposes a backend as the optional `latent` retrieval strategy; off by default |
| `evaluate_information_preservation` | `memoraos.latent.index` | Compares retrieval through the latent state to exact cosine on the same embeddings |
| `memorilla_available()` | `memoraos.latent.base` | True only if a `memorilla` package is importable |

Design rules that hold for every backend:

1. The latent state is a **retrieval aid**; it keeps ids of source memories, so evidence always resolves to original text. It is never the only copy of a fact.
2. The whole application works without it; the strategy is simply unavailable.
3. Backend failures or absence produce `insufficient_evidence` for that stage, not fabricated answers.

## Honest evaluation status

CPU-compatible unit tests check determinism, shapes, compression ratio and that retrieval returns source ids. **No benchmark claims latent memory improves anything**, and none of our reported results use it. The routing layer only considers `latent` when enabled.

## Reproducible plan for a real learned implementation

1. Environment: Linux, CUDA GPU (≥ 80 GB per the Memorilla README), Python 3.11; clone `snap-stanford/memorilla`, download checkpoints (check Qwen3 licences).
2. Implement `LatentMemoryModel` around the released encoder and memory module; expose `memory_tokens(query)`.
3. Add a decoder-side adapter that accepts soft tokens (requires a local HF model; the provider interface currently only has text chat).
4. Evaluate on (a) the project's synthetic suite **with the same extractive scoring**, and (b) LoCoMo/LongMemEval adapters (roadmap) — reporting information preservation (answer accuracy at fixed token budgets), latency and GPU memory.
5. Publish results only from `python -m benchmarks.run` style harnesses with hardware disclosed.

Until step 4 is done, any statement that MemoraOS "uses Memorilla" would be false.
