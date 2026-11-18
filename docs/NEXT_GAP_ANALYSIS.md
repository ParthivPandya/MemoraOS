# MemoraOS Next: gap analysis

Capability gaps against the MemoraOS Next specification, ordered by the specification's own priorities. "Evidence" points to something that exists in this repository. Status of the work done so far is in [NEXT_IMPLEMENTATION_STATUS.md](NEXT_IMPLEMENTATION_STATUS.md).

| Capability | Current implementation | Evidence | Gap | Action | Priority |
|---|---|---|---|---|---|
| Answerable-question recall on real prose | Sentence-level lexical coverage decides answer or abstain | `benchmarks/reports/REAL_DOCS_FAILURES.md`: 15 of 22 missed answerable questions were retrieved and then refused | The support check cannot see paraphrase; a neural embedder is not used by it | Opt-in section and semantic support added (`answerability` policies); **not** the default because the independent set did not confirm the dev gain | P0 |
| Failure classification | Added (`benchmarks/failures.py`) | `REAL_DOCS_FAILURES.md` | 5 of the spec's 14 causes can be told apart on prose documents; extraction, entity, normalization, temporal, conflict and citation causes need datasets that exercise them | Extend when an extraction or temporal dataset exists | P0 |
| Statistical reporting | Wilson intervals, Brier, ECE (`benchmarks/stats.py`) | `ANSWERABILITY_*.md` | Older reports still use bootstrap intervals (degenerate at 100%) | Move the older reports to Wilson | P0 |
| Held-out discipline | Dev, held-out (frozen before v0.2 fixes) and V2 validation sets | `benchmarks/real_docs.py` | The held-out set has now been seen while diagnosing; V2 validation was seen once at the end | Author a V3 set before the next change; never inspect individual V-set questions while designing | P0 |
| Real LLM extraction evaluation | Fakes only | `tests/unit/test_extraction.py` | No Ollama / endpoint here | Run the extraction golden set against a local model when one is available; keep rules as fallback | P0 |
| Neural embeddings | One model measured (MiniLM-L6-v2) on one corpus | `answerability_neural.json` | No Qwen, nomic or other model; no model registry benchmark | Repeat with 2 more models; report cost and latency | P0 |
| Public benchmark adapters | None | issue #3 | LoCoMo, LongMemEval, LongMemEval-V2, MemoryAgentBench, BEAM, PersonaMem, STATE-Bench absent; licences unchecked | One adapter at a time, each with a fixed disclosed judge | P0 |
| Competitor execution | Availability probes, results "not evaluated" | `benchmarks/systems.py` `EXTERNAL` | No Mem0 / Graphiti / Hindsight adapter was run | Implement an adapter only where it can really run; otherwise leave NOT_EVALUATED | P0 |
| Stale fallback value | Passage fallback can return the older of two statements when no fact was extracted | probe in `NEXT_REPOSITORY_AUDIT.md` finding 5 | No recency preference among conflicting passages | Order same-subject passages by recorded or effective date, or report a conflict | P0 |
| Extraction coverage | English rules; possessive / "the P of X" / verbs | `docs/EXTRACTION.md` | "The customer plan is X" yields no fact; relative dates unhandled | Extend with golden-set tests, not one-off rules | P0 |
| Memory CI | Contracts, run, regression diff, CLI | `docs/MEMORY_CI.md` | No automatic triggers, no provider selection on the CLI, no skill / migration hooks | Add `--embedder` / `--settings`, CI template | P1 |
| Entity resolution | Conservative aliases | `docs/MEMORY_DESIGN.md` | No canonical ids, split, history, scope-aware aliases, disambiguation | Schema migration 3 with an entities table | P1 |
| Lifecycle and user controls | `correct`, `verify`, `forget`, `export` | `docs/API.md` | No disputed / archived / expired states, confirm / reject / restore, delete preview | Add states and operations with migration tests | P1 |
| Experience and skills | None | | Whole feature | New tables; promotion needs repeated evidence or approval | P1 |
| Memory Change Sets | None | | Whole feature | Design against the existing event log and authorization | P1 |
| Governance and permissions beyond tenant/user | Tenant, user, level scoping | `docs/SECURITY.md` | No agent-level ACL, no approval policies | With Change Sets | P1 |
| Explainability | `explain()` returns attempts, notes, timeline, contradictions, confidence | `docs/API.md` | No candidate list with scores, no "facts rejected" list | Extend the trace | P1 |
| MCP tools | 6 | `docs/API.md` | Propose / validate / review / evaluate absent | With Change Sets and Memory CI | P1 |
| Dashboard | 6 data pages | `docs/assets/dashboard_*.png` | Lifecycle, change sets, skills, providers, security screens absent | After the backend exists | P1 |
| Encryption, key rotation, signed audit checkpoints | None | issue #4 | Whole feature | SQLCipher feasibility first; never store the key beside the database | P2 |
| ANN, scale measurements | Brute force | `docs/PERFORMANCE.md` | 10^5 limit unmeasured; no 10^3 to 10^6 curve | Measure first, then an optional adapter | P2 |
| Docker | None | issue #5 | Whole feature | Optional minimal image with health check | P2 |
| Multimodal ingestion, connectors, framework adapters, .NET | None | | Whole feature | Only after P0 and P1 defects are closed | P2 |
| Memorilla adapter | Interface plus CPU baseline | `docs/LATENT_MEMORY.md` | No real learned module | Research only after P0 is closed | P3 |
| Presets | None | | Whole feature | Create only from measured configurations | P2 |
| Repository metadata | Description quotes the saturated synthetic result | `gh api repos/ParthivPandya/MemoraOS` | Overclaim | Replace the description (suggestion in the status doc) | P0 |
