# Research and Competitive Analysis

_Compiled 2026-11-17 from primary sources (project READMEs, GitHub metadata via `gh api`, arXiv abstracts). Numbers are **self-reported by the projects** unless stated; the benchmark settings differ between projects (retrieval recall vs. end-to-end QA accuracy, different judges and backbones), so **do not rank systems from the tables below**. We did not run any of these systems. Items we could not verify are marked **UNVERIFIED**._

## 1. Memorilla (Stanford) – the latent-memory reference

**Verified to exist.** Paper: "Memorilla: Latent Semantic Memory for LLMs", arXiv 2610.21375 (Fallahpour, Idehpour, Kothapalli, Mounier, Wu, Pardis, Leskovec). Code: <https://github.com/snap-stanford/memorilla> (Apache-2.0). Site: <https://memory.stanford.edu>; checkpoints: <https://huggingface.co/memorilla>.

| Aspect | What the sources say |
|---|---|
| Idea | A frozen embedding model (Qwen3-Embedding-4B) encodes each document once. A **trainable memory module** attends over the stored embeddings with cross-attention and emits a **fixed number of query-conditioned soft "memory tokens"** in the frozen decoder's (Qwen3-8B) input embedding space. New documents can be added without retraining the LLM. |
| Training | Three stages; GRPO for the TextWorld agent setting; README cites ~19 h on 4×H100. |
| Reported results (self-reported) | With 16 tokens: best on 5 of 8 benchmarks vs. baselines incl. Mem0 and MemoRAG; FactKG 84.33% vs. 80.43% full-context at 108× fewer tokens; 20–4,212× document-token compression; 0.74 s vs. 19.9 s at ~128K tokens (one H100). |
| Requirements | Linux CUDA GPU (README: one 80 GB GPU for the demo), Python 3.11, ~25 GB of model downloads. Windows unsupported per README. No PyPI package found (**UNVERIFIED**). |
| Temporal handling | None documented (**UNVERIFIED** beyond that). |
| Limitations | Memory module tied to one decoder; heavy GPU needs; research code; stored state is opaque (no inspectable text, no per-fact provenance). |

**What MemoraOS does with this.** It does *not* reproduce Memorilla. `memoraos.latent` defines the integration contract (`LatentMemoryBackend`, `LatentMemoryModel`) and ships one CPU baseline (k-means slots + softmax attention readout) clearly labelled experimental. Plugging in a real Memorilla checkpoint is future work that needs a GPU environment. See [LATENT_MEMORY.md](LATENT_MEMORY.md).

## 2. Project comparison

| Project | Core approach | License | Package | Runs locally with no API key? |
|---|---|---|---|---|
| Mem0 | LLM fact extraction/consolidation; semantic + BM25 + entity retrieval fusion | Apache-2.0 | `mem0ai` (pip, npm) | Needs an LLM (default OpenAI); other providers incl. Ollama supported |
| Hindsight (vectorize-io) | Four memory networks; retain / recall / reflect; 4 parallel strategies + RRF + cross-encoder rerank | MIT | `hindsight-api`, `hindsight-all` | Yes with a local LLM; embedded pg0 database |
| MemPalace | Verbatim storage in wings/topics; pluggable vector backend; light temporal graph (SQLite) | MIT | `mempalace` | Yes (core path needs no key) |
| Claude-Mem | Hooks + observer agent → SQLite FTS5 + Chroma; progressive disclosure | Apache-2.0 | `npx claude-mem install` | Partly; observer needs an LLM; fully offline **UNVERIFIED** |
| Cognee | Knowledge graph + vector pipeline; `remember`/`recall` | Apache-2.0 | `cognee` | Yes (local GLiNER + embeddings); backend defaults **UNVERIFIED** |
| Graphiti (Zep) | Bi-temporal knowledge graph with fact invalidation | Apache-2.0 | `graphiti-core` | Needs an LLM and a graph DB server |
| Supermemory | Memory + RAG hybrid; profiles; contradiction/forgetting handling | MIT | `supermemory` | Largely (local embeddings; optional Ollama) |
| Letta (MemGPT) | LLM-managed memory blocks; git-backed context; sleep-time compute | Apache-2.0 | `letta-code` | Needs an LLM |
| LangGraph / LangMem | Checkpointers (thread) + store (cross-thread); LangMem extracts/updates memories | MIT | `langgraph`, `langmem` | LangGraph yes; LangMem needs an LLM |

### Feature matrix (what each project *documents*)

| Capability | Mem0 | Hindsight | MemPalace | Cognee | Graphiti | Supermemory | Letta | MemoraOS |
|---|---|---|---|---|---|---|---|---|
| Local, no key, no server | ✗ (LLM) | ✓ (local LLM) | ✓ | ✓ | ✗ | ~ | ✗ | **✓** |
| Hybrid BM25 + vector | ✓ | ✓ | ~ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Graph / multi-hop | ~ | ✓ | ~ | ✓ | ✓ | ~ | ✗ | ✓ (basic, NetworkX) |
| Bitemporal fact validity | ~ | ✓ (time range) | ✓ (validity windows) | UNVERIFIED | **✓ (core)** | ✓ | ✗ | ✓ (rule-based extraction) |
| Contradiction handling | ✗ | ✓ (beliefs) | ~ | ✗ | ✓ (invalidation) | ✓ | ✗ | ✓ (explicit, reported, never silent) |
| Abstains when unsupported | not documented | not documented | not documented | not documented | not documented | not documented | ✗ | **✓ (measured)** |
| Time-travel ("what did you know on D") | ✗ | ✗ | ✗ | ✗ | ~ | ✗ | git history | ✓ |
| Router that picks a strategy per query | ✗ | parallel + fuse | ✗ | search types | ✗ | ✗ | LLM decides | ✓ (deterministic, observable) |
| Learned latent memory | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | experimental CPU baseline only; Memorilla needs GPU |

"Not documented" means we did not find it in the primary sources, not that it is absent.

## 3. Self-reported benchmark numbers (context only)

| Project | Reported | Source / caveat |
|---|---|---|
| Mem0 | LoCoMo 92.5, LongMemEval 94.4 (new algorithm) | README; self-reported, not independently verified. Older paper (arXiv 2504.19413): +26% relative over OpenAI memory on LLM-judge. |
| Hindsight | LongMemEval up to 91.4%, LoCoMo up to 89.61% | Paper arXiv 2512.12818; authors' evaluation. |
| MemPalace | LongMemEval R@5 96.6% (raw), LoCoMo R@10 60.3–88.9% | **Retrieval recall, not QA accuracy.** The project's own `HISTORY.md` retracts earlier comparisons of recall against competitors' QA accuracy. |
| Supermemory | LongMemEval Recall@15 = 95% | Retrieval recall; "#1" claim unverified. |
| Graphiti/Zep | DMR 94.8% vs. MemGPT 93.4%; up to +18.5% LongMemEval | Paper arXiv 2501.13956; vendor-authored, relative to a baseline. |
| Cognee | BEAM 0.79 @100K tokens (20 questions) | README; exploratory, same set used to select routing. |
| Letta | LoCoMo 74.0% with a filesystem agent | Letta blog; self-reported. |

The MemPalace correction is the cautionary tale this repository is designed around: **comparing different metrics is the easiest way to publish a wrong number.** MemoraOS's benchmark reports external systems as *not executed* instead of quoting these figures.

## 4. Academic references

| Work | Contribution | Link |
|---|---|---|
| Titans (Behrouz et al.) | Neural long-term memory learned at test time | <https://arxiv.org/abs/2501.00663> |
| MemGPT | Virtual context management with memory tiers | <https://arxiv.org/abs/2310.08560> |
| Sleep-time Compute | Offline reasoning about context ("dreaming" consolidation) | <https://arxiv.org/abs/2504.13171> |
| A-MEM | Zettelkasten-style linked notes | <https://arxiv.org/abs/2502.12110> |
| Zep | Temporal knowledge graph for agent memory | <https://arxiv.org/abs/2501.13956> |
| HippoRAG / HippoRAG 2 | KG + Personalized PageRank retrieval; continual learning | <https://arxiv.org/abs/2405.14831>, <https://arxiv.org/abs/2502.14802> |
| LongMemEval (ICLR'25) | 500 questions, 5 memory abilities incl. temporal reasoning and knowledge updates | <https://arxiv.org/abs/2410.10813> |
| LoCoMo | Very long conversational memory QA | <https://arxiv.org/abs/2402.17753> |
| Mem0, Hindsight, Memorilla | see §2–3 | arXiv 2504.19413, 2512.12818, 2610.21375 |
| Reciprocal Rank Fusion (Cormack, Clarke, Buettcher, SIGIR 2009) | Rank fusion used in hybrid retrieval | Link not fetched in this review (**UNVERIFIED**) |

## 5. What already exists vs. where a contribution is possible

**Already exists (we do not claim novelty):** hybrid BM25 + vector + RRF; temporal knowledge graphs with fact invalidation (Graphiti/Zep, MemPalace); retain/recall/reflect (Hindsight); LLM-driven consolidation ("dreaming", Letta); learned latent memory tokens (Memorilla); time-range recall (Hindsight).

**Gaps we identified (from documentation, not exhaustive):**

1. **No local-first system combines all of**: temporal validity, explicit contradiction reporting, abstention, per-query routing and an audit trail in a single dependency-light package (SQLite + NumPy + NetworkX). Most strong temporal systems need an LLM at ingest and often a graph server.
2. **Abstention is rarely measured.** None of the benchmarks above report an *unsupported-answer rate*. MemoraOS reports it directly (and in our synthetic suite, always-answering RAG baselines answer 37.5% (BM25) to 100% (vector, hybrid) of unanswerable questions, versus 0% for MemoraOS on this suite).
3. **Evidence-preserving consolidation with rollback** (derived memories link to originals, never overwrite facts, runs reversible) is not described by the surveyed systems.
4. **"What did the system know on date D?"** with a hash-chained event log is not described by the surveyed systems (LangGraph checkpoints give state time-travel, not semantic).
5. **Reproducible, executable comparison**: the field mixes metrics. A deterministic harness that refuses to quote unrun competitors is itself a contribution.

**Where MemoraOS is weak (honest):**

- Fact extraction is rule-based English. On our `paraphrase_robustness` scenario MemoraOS (77.1%) is *below* plain RAG baselines (100%) because its strict evidence checks abstain on phrasings its rules do not cover (see [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)). LLM-assisted extraction through the `EntityExtractor` interface is the planned fix, with measurement.
- The default embedder is lexical; paraphrase-level semantic retrieval needs a neural embedder (Ollama / OpenAI-compatible adapters exist but are not benchmarked here).
- Latent memory is an interface plus a CPU baseline; no learned module was trained.

## 6. Licensing and patent considerations

- No code from the surveyed projects is copied or vendored. Designs are independent; ideas (RRF, bitemporal validity, memory tokens) are published research.
- Runtime dependencies are permissively licensed: NumPy (BSD-3), NetworkX (BSD-3), Pydantic (MIT), httpx (BSD-3); optional FastAPI (MIT), Uvicorn (BSD-3). MemoraOS is Apache-2.0. Dashboard: Next.js/React (MIT).
- Memorilla is Apache-2.0, so a future adapter could import it; its model checkpoints have their own terms (Qwen3 licences) that must be checked before bundling. LoCoMo's repository license is NOASSERTION; do not redistribute its data without reading its terms.
- We did **not** conduct a patent search. Temporal knowledge graphs and memory-augmented LLMs are active patent areas; commercial users should do their own freedom-to-operate review.

## 7. Explicitly unverified assumptions

- Memorilla's exact per-benchmark numbers and whether LoCoMo / LongMemEval are among its eight benchmarks.
- Whether Memorilla has a PyPI package; whether Claude-Mem runs fully offline; Cognee's temporal semantics and default backends; Graphiti's exact field names and Kuzu support.
- Whether Titans, A-MEM and MemGPT full papers report conversational-memory benchmarks.
- All vendor-reported accuracy numbers above.
- The RRF paper link.

## 8. Proposed differentiation (and how it is tested)

| Claim | Test |
|---|---|
| Correct current / historical values under repeated updates | `temporal_reasoning`, `historical_reconstruction`, `degradation_after_updates` |
| Conflicts flagged, version changes not flagged | `contradiction_resolution` |
| Does not answer when memory is silent | `unsupported_answers`, `historical_reconstruction` (before-known) |
| Consolidation preserves originals | `memory_consolidation` (originals intact 100%, modified 0) |
| Survives restart | `persistence_after_restart` |
| Honest limitation | `paraphrase_robustness` |

Results: [BENCHMARK_METHODOLOGY.md](BENCHMARK_METHODOLOGY.md) and `benchmarks/reports/REPORT.md`.
