# Competitive intelligence: AI-agent memory systems and benchmarks

Research date: 2026-11-18. Every row below comes from public documentation: official GitHub
repositories and READMEs, official documentation sites, dataset cards, and arXiv papers. Each claim
has its source URL next to it. Anything not found in a primary source is marked "not verified".
Benchmark numbers are copied as published and labelled "self-reported by vendor" where the vendor
ran the evaluation. No number here was estimated or re-run by this project. MemoraOS has not been
run against any system listed here; its retrieval-only runs on two of the datasets are in PUBLIC_BENCHMARKS.md.

## Comparison table

| System | Local / no API key | Temporal handling | Evidence returned | Licence | Source |
|---|---|---|---|---|---|
| Mem0 | OSS library needs an LLM; Ollama LLM and embedder are documented; a "fully local, no API keys" Ollama config exists in the benchmark repo | OSS: ADD-only, nothing overwritten. Platform v3 only: temporal ranking boost. Not in OSS | Returns memory text; link to source message not verified | Apache-2.0 | github.com/mem0ai/mem0 |
| Zep / Graphiti | Graphiti: needs a graph DB plus an LLM; Ollama documented with caveats for small models. Zep: managed service or BYOC | Explicit bi-temporal edges with validity windows; invalidation, not deletion | Facts trace back to source episodes (provenance) | Apache-2.0 (Graphiti, zep repo); Zep service licence not verified | github.com/getzep/graphiti |
| Letta (MemGPT) | Local backend stores state on local disk; whether a no-key local-model setup is documented: not verified | Git version history of memory edits; no validity-window model found | Not verified | Apache-2.0 | github.com/letta-ai/letta-code |
| Cognee | Yes: README states local run with no API key using GLiNER and local embeddings; retrieval returns passages, no generated answer | Not verified | Recall results are tagged with a `source` field; retrieved context is inspectable | Apache-2.0 | github.com/topoteretes/cognee |
| LangMem | README configures an LLM provider API key; no-key setup: not verified | LLM-driven consolidation; no explicit time model found | Not verified | MIT | github.com/langchain-ai/langmem |
| Supermemory | Local server documented; text memories can run offline via Ollama after the first embedding-model download | README claims contradiction handling and expiry of temporary facts | Not verified | MIT | github.com/supermemoryai/supermemory |
| Memorilla | No API key: local Hugging Face models; needs Linux and a CUDA GPU (80 GB used in README) | Not verified | Output is 16 latent memory tokens for the LLM; no citation mechanism described | Apache-2.0 | github.com/snap-stanford/memorilla |

- Licence facts come from the GitHub licence metadata of each repository
  (https://api.github.com/repos/OWNER/REPO, queried 2026-11-18) and, where noted, the README.

## Systems

### Mem0
- Sources: https://github.com/mem0ai/mem0, https://docs.mem0.ai, https://arxiv.org/abs/2504.19413
- Architecture: memory layer with User, Session and Agent levels; the library, a self-hosted server
  and a cloud platform are separate deployment options
  (https://raw.githubusercontent.com/mem0ai/mem0/main/README.md). Retrieval fuses semantic, BM25
  keyword and entity matching (same README). The how-it-works page lists vector, entity and history
  stores (https://docs.mem0.ai/llms.txt).
- Updates and contradictions: the April 2026 algorithm is "single-pass ADD-only extraction ... no
  UPDATE/DELETE. Memories accumulate; nothing is overwritten" (same README). Explicit edit and
  history endpoints also exist (https://docs.mem0.ai/llms.txt).
- Time: "Temporal Reasoning" boosts memories whose event dates match the time in the query; "It is
  not available in the OSS SDK" (https://docs.mem0.ai/platform/features/temporal-reasoning).
- Evidence: the README example reads `entry['memory']` from search results
  (https://raw.githubusercontent.com/mem0ai/mem0/main/README.md). Citation back to the source
  message: not verified.
- Local, no key: README says Mem0 requires an LLM (default `gpt-5-mini`) and default embeddings
  `text-embedding-3-small` (same README). Ollama is documented as LLM provider
  (https://docs.mem0.ai/components/llms/models/ollama) and embedder
  (https://docs.mem0.ai/components/embedders/models/ollama); each doc example still sets
  `OPENAI_API_KEY` for the other component. The benchmark repo lists `configs/ollama.yaml` as
  "Fully local with Ollama (no API keys)" (https://raw.githubusercontent.com/mem0ai/memory-benchmarks/main/README.md).
- Licence: Apache-2.0 (https://api.github.com/repos/mem0ai/mem0).
- Benchmark numbers, self-reported by vendor. Setting per the README: managed platform, single-pass
  retrieval, top_200; the platform "includes proprietary optimizations not available in the
  open-source SDK" (https://raw.githubusercontent.com/mem0ai/mem0/main/README.md). LoCoMo 71.4 (old)
  to 92.5 (new); LongMemEval 67.8 to 94.4; BEAM 1M 64.1; BEAM 10M 48.6 (no old values). The metric is
  not named in the table. The benchmark repo defaults to a `gpt-4o` answerer and judge (benchmark repo
  README); that these defaults produced the published numbers is not verified.
- Paper, earlier algorithm, self-reported: LoCoMo "26% relative improvements in the LLM-as-a-Judge
  metric over OpenAI", 91% lower p95 latency, over 90% token saving vs full-context
  (https://arxiv.org/abs/2504.19413).

### Zep and Graphiti
- Sources: https://github.com/getzep/graphiti, https://arxiv.org/abs/2501.13956
- Architecture: Graphiti is an open-source Python framework for temporal context graphs; entities,
  facts as edges with validity windows, and episodes as raw-data provenance. Graph backends:
  Neo4j, FalkorDB, Amazon Neptune. Zep is the managed service built on Graphiti
  (https://raw.githubusercontent.com/getzep/graphiti/main/README.md).
- Time and contradictions: "Facts have validity windows. When information changes, old facts are
  invalidated, not deleted"; the README table states "Explicit bi-temporal tracking with automatic
  fact invalidation" (same README). The paper prompts define `valid_at` and `invalid_at`
  (https://arxiv.org/html/2501.13956v1).
- Evidence: "Every entity and relationship traces back to the episodes (raw data) that produced it"
  (https://raw.githubusercontent.com/getzep/graphiti/main/README.md).
- Local, no key: requirements list a graph database and, by default, an OpenAI key. Ollama through an
  OpenAI-compatible endpoint is documented; the README warns very small models "frequently emit JSON
  that doesn't match the requested schema". Embedded FalkorDB needs Python 3.12 or later. Zep is
  "managed or BYOC", Graphiti "self-hosted only" (same README).
- Licence: Apache-2.0 for graphiti and the zep repository
  (https://api.github.com/repos/getzep/graphiti, https://api.github.com/repos/getzep/zep).
- Benchmark numbers, self-reported by the Zep authors (https://arxiv.org/html/2501.13956v1): DMR
  94.8% versus 93.4% for MemGPT. LongMemEval, GPT-4o judge, run December 2024 to January 2025 against
  Zep's hosted service: gpt-4o-mini 63.8% (Zep) versus 55.4% (full-context); gpt-4o 71.2% versus
  60.2%; average context 1.6k versus 115k tokens. Zep scored lower on single-session-assistant
  (75.0% versus 81.8% gpt-4o-mini; 80.4% versus 94.6% gpt-4o). MemGPT could not be run on
  LongMemEval, so there is no head-to-head there.

### Letta (formerly MemGPT)
- Sources: https://github.com/letta-ai/letta, https://docs.letta.com/concepts/memfs,
  https://docs.letta.com/self-hosting/app-server
- Status: the README says current source lives in `letta-ai/letta-code` and the V1 API server is
  archived (https://raw.githubusercontent.com/letta-ai/letta/main/README.md).
- Architecture: MemFS, a git repository of Markdown files with YAML frontmatter, edited by the agent
  with file tools; root files load into the system prompt every turn. No vector index by default;
  keyword or semantic search comes from an optional mod (https://docs.letta.com/concepts/memfs).
  The older V1 SDK used memory blocks (https://docs.letta.com/v1-sdk).
- Updates and time: every memory edit is committed to git, giving version history and conflict
  resolution (https://docs.letta.com/concepts/memfs). A validity-window or bitemporal model: not found.
- Evidence: not verified.
- Local, no key: with the `local` backend, state is stored in `~/.letta/lc-local-backend`
  (https://docs.letta.com/self-hosting/app-server); local conversation search is full-text only
  (https://docs.letta.com/concepts/memfs). Use of an LLM without any provider key: not verified.
- Licence: Apache-2.0 for letta and letta-code (https://api.github.com/repos/letta-ai/letta,
  https://api.github.com/repos/letta-ai/letta-code).
- Benchmark numbers published by Letta: not verified (none found on the pages read).

### Cognee
- Sources: https://github.com/topoteretes/cognee, https://docs.cognee.ai
- Architecture: text becomes entities, relationships and searchable chunks; code becomes a graph of
  symbols. Operations: `remember`, `recall`, `improve`, `forget`. Vector, graph and relational
  stores; the whole layer can run on one Postgres instance, marked a demo feature
  (https://raw.githubusercontent.com/topoteretes/cognee/main/README.md).
- Time and contradictions: not verified. The documentation index contains no temporal page.
- Evidence: each recall result carries a `source` field such as "graph" or "session"
  (https://docs.cognee.ai/core-concepts/main-operations/recall). The README says the application
  "can inspect the retrieved evidence". With no LLM, recall returns the assembled context, not an answer.
- Local, no key: "Runs locally for free, no API key required"; local GLiNER extraction and embeddings
  download on first use; generated answers need an LLM (https://raw.githubusercontent.com/topoteretes/cognee/main/README.md).
- Licence: Apache-2.0 (https://api.github.com/repos/topoteretes/cognee).
- Benchmark numbers, self-reported by vendor, BEAM with an LLM judge
  (https://raw.githubusercontent.com/topoteretes/cognee/main/README.md): 0.79 at 100K tokens (fixed
  hybrid retrieval, four rounds over 20 questions from one held-out conversation); 0.67 at 10M tokens
  (exploratory; routing selected and scored on the same questions).

### LangMem
- Sources: https://github.com/langchain-ai/langmem,
  https://langchain-ai.github.io/langmem/concepts/conceptual_guide/
- Architecture: a library of memory primitives that works with any storage, plus LangGraph store
  integration. Memory types: semantic, episodic, procedural. Memory tools run in the hot path, or a
  background manager extracts and consolidates (https://raw.githubusercontent.com/langchain-ai/langmem/main/README.md).
  The README example uses `InMemoryStore`, which loses data on restart.
- Updates and contradictions: each operation prompts an LLM to expand or consolidate the memory state;
  the system "must reconcile new information with previous beliefs, either deleting/invalidating or
  updating/consolidating" (conceptual guide URL above). Explicit validity times: not found.
- Evidence: not verified.
- Local, no key: README says to configure an LLM provider API key; keyless setup: not verified.
- Licence: MIT (https://api.github.com/repos/langchain-ai/langmem).
- Benchmark numbers: not verified (none found on the pages read).

### Supermemory
- Sources: https://github.com/supermemoryai/supermemory, https://supermemory.ai/research
- Architecture: memory engine, user profiles (static and dynamic), hybrid search over memories and
  documents, connectors, file processing (https://raw.githubusercontent.com/supermemoryai/supermemory/main/README.md).
- Updates and contradictions: the README says it "tracks updates, resolves contradictions,
  auto-forgets expired info" ("I just moved to SF" supersedes "I live in NYC") (same README). The
  mechanism and any stored-time model: not verified.
- Evidence: the quickstart returns `searchResults` ranked by similarity. Source citation: not verified.
- Local, no key: "Offline text memories if you want": point it at Ollama, disable telemetry, and use
  text or file inputs after the first embedding-model download; default local embeddings
  `Xenova/bge-base-en-v1.5`; URL ingestion uses a hosted reader service (same README).
- Licence: MIT (https://api.github.com/repos/supermemoryai/supermemory).
- Benchmark claims, self-reported by vendor (same README): "#1" on LongMemEval, LoCoMo and ConvoMem,
  with no comparison set or table. On LongMemEval: "95% Recall@15 while adding only ~720 tokens of
  context" (99.4% reduction); recall by category: knowledge updates 99%, assistant 100%, user 97%,
  multi-session 93%, temporal 91%, preference 90%. LongMemEval variant and recall definition: not
  verified. The research page was not read.

### Memorilla
- Sources: https://github.com/snap-stanford/memorilla, https://arxiv.org/abs/2610.21375,
  https://memory.stanford.edu
- What it is: a trained memory module that turns a document collection into 16 query-dependent
  "memory tokens" placed in a frozen LLM's input embedding space
  (https://raw.githubusercontent.com/snap-stanford/memorilla/main/README.md).
- Local, no key: Linux, CUDA GPUs and Python 3.11; recipes ran on H100 80 GB; the example downloads
  about 25 GB of models (same README).
- Time, contradictions, evidence: not verified. The README describes no citation mechanism.
- Licence: Apache-2.0 for code (https://api.github.com/repos/snap-stanford/memorilla). Datasets:
  PersonalizationV4 CC-BY-4.0, Memorilla-Data "other" (https://huggingface.co/api/datasets/memorilla/Memorilla-Data).
- Numbers, self-reported by the authors (https://arxiv.org/abs/2610.21375): with 16 memory tokens,
  best against baselines including Mem0 and MemoRAG on five of eight benchmarks; FactKG 84.33% versus
  80.43% full-context with 108x fewer tokens; TextWorld success 18.6% (full-history in-context) to
  24.2%. Whether LongMemEval or LoCoMo is among the eight benchmarks: not verified.

## Benchmarks

| Benchmark | Measures | Size | Licence | Format | Hosted at | Retrieval-only scoring without LLM judge |
|---|---|---|---|---|---|---|
| LongMemEval | 5 abilities: extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention | 500 questions | MIT (repo, HF card) | JSON | Hugging Face | Yes, documented |
| LoCoMo | Long-conversation QA, event summarisation, multimodal dialogue | 10 conversations (released subset) | CC BY-NC 4.0 text in LICENSE.txt | JSON | GitHub | Possible from evidence ids; scoring script not verified |
| MemoryAgentBench | Accurate retrieval, test-time learning, long-range understanding, conflict resolution or selective forgetting | 146 rows on HF | MIT | Parquet | GitHub and HF | Not verified; documented metrics are answer-level |

### LongMemEval
- Sources: https://arxiv.org/abs/2410.10813, https://github.com/xiaowu0162/LongMemEval
- Measures: five abilities, 500 questions over timestamped user-assistant histories
  (https://arxiv.org/abs/2410.10813). ICLR 2025.
- Variants: `longmemeval_s` about 115k tokens, about 40 sessions; `longmemeval_m` about 500 sessions;
  `longmemeval_oracle` with evidence sessions only
  (https://raw.githubusercontent.com/xiaowu0162/LongMemEval/main/README.md).
- Format: JSON; per question `question_id`, `question_type`, `question`, `answer`, `question_date`,
  `haystack_session_ids`, `haystack_dates`, `haystack_sessions`, `answer_session_ids`; evidence turns
  carry `has_answer: true`; abstention ids end `_abs` (same README).
- Hosting: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned (cleaned September 2025;
  an earlier uncleaned version exists).
- Licence: MIT for the HF dataset (https://huggingface.co/api/datasets/xiaowu0162/longmemeval-cleaned)
  and the GitHub repo (https://api.github.com/repos/xiaowu0162/LongMemEval).
- Retrieval-only: yes. `answer_session_ids` supports session-level recall and `has_answer` supports
  turn-level recall; `print_retrieval_metrics.py` prints metrics, and the 30 abstention instances are
  skipped for retrieval evaluation. Question answering is scored by an LLM judge (`evaluate_qa.py`
  with `gpt-4o`) (same README).

### LoCoMo
- Sources: https://arxiv.org/abs/2402.17753, https://github.com/snap-research/locomo
- Measures: question answering, event summarisation and multimodal dialogue generation over very
  long conversations; the paper reports 300 turns and 9K tokens on average, up to 35 sessions
  (https://arxiv.org/abs/2402.17753).
- Size: ten conversations in the released subset; an earlier release had 50 (README Note 1). QA pair
  count: not verified from LoCoMo's own pages (Mem0's benchmark repo lists "~300" but counts 1540).
- Format: `data/locomo10.json`; per sample `conversation` (`session_<n>`, `session_<n>_date_time`, turns
  with `speaker`, `dia_id`, `text`), `qa` (`question`, `answer`, `category`, `evidence` dialog ids "when
  available"), plus generated `observation` and `session_summary` (https://github.com/snap-research/locomo).
- Hosting: GitHub, in the repository above.
- Licence: LICENSE.txt contains the CC BY-NC 4.0 text
  (https://raw.githubusercontent.com/snap-research/locomo/main/LICENSE.txt); GitHub reports
  NOASSERTION (https://api.github.com/repos/snap-research/locomo/license).
- Retrieval-only: `evidence` dialog ids allow turn-level recall without an LLM judge; no such
  scoring script was found in the README. Event-summarisation evaluation is "Coming soon".

### MemoryAgentBench
- Sources: https://arxiv.org/abs/2507.05257, https://github.com/HUST-AI-HYZ/MemoryAgentBench,
  https://huggingface.co/datasets/ai-hyz/MemoryAgentBench
- Measures: the paper names accurate retrieval, test-time learning, long-range understanding and
  selective forgetting; the README labels the fourth "Conflict Resolution". Long contexts are chunked
  into multi-turn injection; EventQA and FactConsolidation are newly built; others are reformulated
  from existing datasets. ICLR 2026.
- Size and format: HF viewer shows 146 rows in 4 splits, Parquet, fields `context`, `questions`,
  `answers`, `metadata` (HF dataset page).
- Licence: MIT for the code repository and the HF dataset
  (https://api.github.com/repos/HUST-AI-HYZ/MemoryAgentBench,
  https://huggingface.co/api/datasets/ai-hyz/MemoryAgentBench).
- Scoring: `substring_exact_match` or `exact_match` for most tasks, Recall@5 for the recommender task,
  and LLM-as-judge only for the LongMemEval and InfBench-summarisation subsets (README metric table).
  Session or turn recall without an LLM: not verified. Baseline runs need API keys.

## What MemoraOS can honestly claim

Basis: this project's own README (README.md lines 8, 37, 55, 57).

- Local-first: the project describes itself as a local-first temporal memory engine.
- Bitemporal facts: valid time and recorded time are kept; nothing is overwritten. Graphiti also
  documents bi-temporal tracking, so this is not unique.
- Evidence on every answer: source id, excerpt, effective date and reliability are returned.
- Explicit abstention: the engine returns `insufficient_evidence` instead of guessing.
- Reproducible benchmarks on project-authored data: the project's published tables use its own
  documents and synthetic data, scored by a mechanical (non-LLM) judge, regenerated by scripts.
  The README itself states that on real prose MemoraOS is not ahead of a tuned RAG baseline.

## What MemoraOS cannot claim

- Any superiority over Mem0, Zep/Graphiti, Letta, Cognee, LangMem, Supermemory or Memorilla.
  No head-to-head run exists.
- Any public benchmark *score*. MemoraOS has only been run retrieval-only on LoCoMo and a 60-question LongMemEval-S sample ([PUBLIC_BENCHMARKS.md](PUBLIC_BENCHMARKS.md)), where plain BM25 was at least as good; it has not been run on MemoryAgentBench, and no answer-accuracy run exists. Those numbers are not comparable to the vendor-reported scores above.
- Uniqueness of local operation: Cognee, Supermemory, Mem0 and Graphiti each document some local setup.
