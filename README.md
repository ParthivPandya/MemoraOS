# MemoraOS

**Don't just give AI a bigger context window. Give it a better memory.**

MemoraOS is a local-first, open-source memory engine for AI agents. It stores what an agent is told, understands how facts change over time, answers with traceable evidence, **says so when memory does not establish an answer**, and ships a reproducible benchmark so its claims can be checked. No API key, cloud service or Docker is required.

> **Status: v0.1 (alpha).** Core engine, REST API, SDKs, MCP server and dashboard work and are tested (132 automated tests). Learned latent memory is experimental and is **not** Stanford Memorilla. See [Limitations](#limitations).

## The problem

Vector search over chat history fails in predictable ways: it returns an old salary next to the new one, mixes up two documents that disagree, cannot link facts spread over five notes, answers confidently when memory is silent, and cannot tell you what the agent knew last month. MemoraOS treats those as first-class requirements:

| Need | How MemoraOS handles it |
|---|---|
| Facts change | Bitemporal facts (valid time + recorded time); nothing is overwritten; current / historical / previous queries |
| Documents disagree | Explicit contradiction analysis: version changes resolve, real conflicts are **reported, not silently picked** |
| Answers must be trustworthy | Evidence (source ids, excerpts, effective dates, reliability, verification) and `insufficient_evidence` when unsupported |
| Different questions need different retrieval | Deterministic adaptive router with observable strategy and fallbacks |
| Memory must be inspectable | Originals are never altered or lost; consolidation only adds linked, reversible summaries |
| "What did the agent know on date D?" | Time travel over versions + hash-chained event log |
| Privacy | Tenant/user isolation, secret redaction, hard delete, export, untrusted-data rendering for prompt-injection safety |

## Architecture

```
 remember()                                         recall()
     │                                                  │
 ingestion: redact → chunk → classify → facts/entities/dates → dedup → embed (cached)
     │                                                  │
     ▼                                                  ▼
 SQLite (WAL): sources · memories+versions · FTS5 · embeddings · facts · mentions · links · events    router → strategy → fallbacks
                                                         │      exact · temporal · bm25 · vector · hybrid · graph · episodic · procedural · multistage · latent(exp.)
                                                         ▼
                              truth engine: timelines · contradictions · reliability · support check → answer + evidence + confidence signals
```

Full diagram, schema, contracts and risk register: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Install

```bash
git clone https://github.com/<you>/memora-os && cd memora-os
python -m venv .venv && .venv\Scripts\activate        # Windows; use source .venv/bin/activate on Linux/macOS
pip install -e ".[dev,api]"
```

Requires Python 3.10+. Core dependencies: NumPy, NetworkX, Pydantic, httpx (SQLite ships with Python). `api` adds FastAPI + Uvicorn.

## Five-minute quick start

```python
from memoraos import MemoryOS

memory = MemoryOS.local()                       # ./.memoraos, no network, no keys

memory.remember("The user is building an AI orchestration platform", user_id="user_001")
memory.remember("Parth's salary is ₹28 LPA in 2024.", user_id="user_001")
memory.remember("Parth's salary is ₹32 LPA in 2026.", user_id="user_001")

result = memory.recall("What AI platform is the user building?", user_id="user_001")
print(result.answer)      # The user is building an AI orchestration platform
print(result.evidence)    # memory ids, source ids, excerpts, reliability, dates
print(result.strategy)    # hybrid

print(memory.recall("What is Parth's current salary?", user_id="user_001").answer)      # ₹32 LPA
print(memory.recall("What was Parth's salary in 2024?", user_id="user_001").answer)     # ₹28 LPA
print(memory.recall("What is Parth's blood group?", user_id="user_001").status)        # insufficient_evidence
```

More: `memory.explain(result.recall_id, user_id=…)`, `memory.history(subject="Parth", predicate="salary", user_id=…)`, `memory.recall(q, as_of="2025-06-01", …)`, `memory.correct(…)`, `memory.forget(…)`, `memory.consolidate(…)`, `memory.reflect(…)`, `memory.evaluate(…)`. Full reference: [docs/API.md](docs/API.md).

### Run everything

```bash
memoraos keys create --tenant default --role admin     # prints an API key once
memoraos serve                                         # REST API on http://127.0.0.1:8000  (docs at /docs)
python -m pytest                                       # 132 tests
python -m benchmarks.run                               # benchmark lab (~2 min) -> benchmarks/reports/
python examples/basic_memory/main.py                   # examples: basic_memory, temporal_memory, hybrid_rag, multi_agent, research_memory
cd apps/dashboard && copy .env.example .env.local && npm install && npm run dev    # http://localhost:3000
cd sdk/typescript && npm install && npm test           # TypeScript SDK
MEMORAOS_USER_ID=user_001 memoraos mcp                 # MCP server over stdio
```

Set `MEMORAOS_API_KEY` in `apps/dashboard/.env.local` to the key printed above (the dashboard keeps it server-side).

## Memory types

Episodic (what happened), semantic (facts, preferences), procedural (how-to), temporal (values over time), relational (entity graph, multi-hop), latent (experimental). Details: [docs/MEMORY_DESIGN.md](docs/MEMORY_DESIGN.md).

## Adaptive routing

A deterministic router scores each question (exact / temporal / multi-hop / procedural / episodic / summary / semantic), picks the cheapest strategy among the best, and lists fallbacks. The choice is returned on every result:

| Question | Strategy |
|---|---|
| "What is my exact current salary?" | `exact` (fact timeline) |
| "What was Parth's salary in 2025?" | `temporal` |
| "How is Alice related to Azure Functions?" | `graph` |
| "How do I deploy Project Atlas?" | `procedural` |
| "What happened before the migration failed?" | `episodic` |
| "Find error E4021" | `bm25` |
| "Summarize everything about AI memory" | `multistage` |

Feedback-driven strategy learning exists but is **off by default** and cannot trade accuracy for cost. [docs/ADAPTIVE_ROUTING.md](docs/ADAPTIVE_ROUTING.md).

## Benchmarks

`python -m benchmarks.run` generates deterministic datasets for 14 required scenarios plus a robustness scenario, runs the systems and writes `benchmarks/reports/REPORT.md` (+ JSON). Snapshot from the committed report (3 seeds, ≈850 questions, synthetic project-authored data, lexical hashing embedder, no LLM anywhere, 95% bootstrap CIs; hardware and digest in the report):

| System | Pooled accuracy [95% CI] | Unsupported-answer rate¹ |
|---|---|---|
| BM25 RAG | 65.2% [62.2, 68.4] | 37.5% |
| Vector RAG | 69.9% [66.8, 72.9] | 100% |
| Hybrid RAG (RRF) | 62.8% [59.7, 66.0] | 100% |
| Hybrid RAG + abstention gate | 64.2% [60.9, 67.3] | 50.0% |
| MemoraOS forced to hybrid (ablation) | 58.0% [54.6, 61.4] | 0% |
| **MemoraOS** | **97.2% [96.0, 98.2]** | **0%** |

¹ share of unanswerable questions in the `unsupported_answers` scenario that received an answer (lower is better).

What this does and does not show: MemoraOS wins where its mechanisms apply (temporal, historical, update, contradiction, multi-hop, multi-document, abstention). **It loses on paraphrase robustness (77.1% vs. 100% for plain RAG)** because its rule-based fact extraction and strict support check abstain on phrasings they do not cover. It also costs more per write (≈13.7 vs. 2.7 ms) and per query (≈6.5 vs. ≈2 ms) and stores more. The datasets are ours, so these numbers demonstrate mechanisms, not superiority on real data. Mem0, Graphiti, Hindsight and Memorilla were **not run**; the report says why. Method and limits: [docs/BENCHMARK_METHODOLOGY.md](docs/BENCHMARK_METHODOLOGY.md).

## Comparison with other systems (documented capabilities only)

| | Local, no key, no server | Bitemporal facts | Contradiction reporting | Abstention measured | Learned latent memory |
|---|---|---|---|---|---|
| MemoraOS | yes | yes (rule-based extraction) | yes | yes | experimental baseline only |
| Mem0 | needs an LLM | partial | no | not documented | no |
| Graphiti / Zep | needs LLM + graph DB | yes (core strength) | invalidation | not documented | no |
| Hindsight | yes with a local LLM | time-range recall | beliefs | not documented | no |
| Memorilla | needs Linux + CUDA GPU | none documented | none documented | no | **yes (the reference)** |

Sources, licenses, verified vs. unverified claims and self-reported numbers: [docs/RESEARCH_AND_COMPETITIVE_ANALYSIS.md](docs/RESEARCH_AND_COMPETITIVE_ANALYSIS.md). Those projects are mature and often stronger on semantic extraction; MemoraOS's niche is local, inspectable, temporally-correct, abstaining memory.

## Limitations

- Fact extraction is deterministic English rules; paraphrased/implicit statements may not become facts (measured).
- Default embeddings are lexical (feature hashing); use `OllamaEmbedder` / `OpenAICompatEmbedder` for semantic recall (not yet benchmarked).
- Latent memory: an interface and a CPU k-means baseline. **No Memorilla reproduction**, no trained module, no benchmark benefit claimed.
- Brute-force vector search (fine to ~10⁵ memories); no encryption at rest in code; backups are not rewritten on delete. See [docs/SECURITY.md](docs/SECURITY.md), [docs/PERFORMANCE.md](docs/PERFORMANCE.md).

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [API](docs/API.md) · [Memory design](docs/MEMORY_DESIGN.md) · [Adaptive routing](docs/ADAPTIVE_ROUTING.md) · [Temporal memory](docs/TEMPORAL_MEMORY.md) · [Latent memory](docs/LATENT_MEMORY.md) · [Benchmark methodology](docs/BENCHMARK_METHODOLOGY.md) · [Research](docs/RESEARCH_AND_COMPETITIVE_ANALYSIS.md) · [Security](docs/SECURITY.md) · [Performance](docs/PERFORMANCE.md) · [Roadmap](docs/ROADMAP.md) · [Implementation status](docs/IMPLEMENTATION_STATUS.md)

## Roadmap

Fix the paraphrase weakness with optional LLM-assisted extraction; LoCoMo/LongMemEval adapters; executable Mem0/Graphiti/Hindsight baselines; ANN index; encryption at rest; Memorilla adapter on a GPU host. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Good first contributions: a benchmark scenario that makes MemoraOS look bad, an extraction rule with a test, an external-system adapter that really runs. Security issues: [SECURITY.md](SECURITY.md).

License: [Apache-2.0](LICENSE).
