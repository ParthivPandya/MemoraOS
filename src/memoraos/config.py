"""Runtime configuration with validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator

# policy -> (section-support coverage, semantic-support cosine); None = off. strict is exactly the v0.2 behaviour.
# The non-strict numbers are PROVISIONAL until docs/NEXT_ANSWERABILITY.md records the dev measurement that chose
# them. The semantic threshold applies only with a neural embedder (it is meaningless for lexical hashing).
ANSWERABILITY_POLICIES: dict[str, tuple[float | None, float | None]] = {
    "strict": (None, None), "balanced": (0.6, 0.55), "high_recall": (0.5, 0.45), "extractive_only": (0.6, 0.55),
}


class Settings(BaseModel):
    """All tunables in one validated place. Every value has a documented reason."""

    data_dir: Path = Field(default=Path("./.memoraos"), description="Directory for the SQLite file and source copies.")
    db_filename: str = "memoraos.db"
    encryption_passphrase: str | None = Field(
        default=None, repr=False, exclude=True,
        description="Encrypt the database file at rest (AES-256-GCM; needs memoraos[encryption]). Falls back to the MEMORAOS_ENCRYPTION_KEY environment variable. Never serialised.",
    )

    # Retrieval
    default_top_k: int = Field(default=5, ge=1, le=200)
    candidate_pool: int = Field(default=50, ge=5, le=1000, description="Candidates per retriever before fusion.")
    rrf_k: int = Field(default=60, ge=1, description="Reciprocal-rank-fusion constant from Cormack et al. (2009).")
    min_evidence_coverage: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Fraction of query terms the evidence must cover to answer."
    )
    min_anchor_coverage: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="When an answer is composed of more sentences than the strategy asked for, its best single sentence must cover at least this fraction of the question's terms on its own.",
    )
    answer_max_sentences: int = Field(
        default=3, ge=1, le=5,
        description="Passage answers may quote up to this many sentences; a further sentence is added only while it covers a question term not yet covered.",
    )
    head_guard_coverage: float = Field(
        default=0.75, ge=0.0, le=1.01,
        description="Evidence must mention the attribute the question ends with, unless it already covers at least this fraction of the question's terms (1.01 = always require it, the v0.1 behaviour).",
    )
    max_graph_hops: int = Field(default=6, ge=1, le=8)
    answerability: str = Field(
        default="strict",
        description="strict (v0.2 behaviour) | balanced | high_recall | extractive_only. Policies differ in how much section-level evidence may support an answer (see docs/NEXT_ANSWERABILITY.md).",
    )
    memory_support_coverage: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Override: a memory whose whole text covers at least this fraction of the question's terms may support a windowed answer even when no single sentence does. None = taken from the policy (strict: off).",
    )
    semantic_support: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Override: with a NEURAL embedder, a sentence whose cosine similarity to the question is at least this may support a windowed answer. Ignored (with a note in explain()) for the lexical hashing embedder. None = from the policy.",
    )
    memory_window: int = Field(default=1, ge=0, le=3, description="Sentences taken on each side of the best-covering sentence for a section- or semantically-supported answer.")
    evidence_fusion: bool = Field(default=True, description="Answer chain questions ('the project Alice manages') by typed path search over facts.")
    evidence_max_hops: int = Field(default=4, ge=2, le=6, description="Longest chain of facts evidence fusion will follow.")
    evidence_max_paths: int = Field(default=50, ge=1, le=500)
    evidence_max_expansions: int = Field(default=5000, ge=100, le=100000, description="Hard cap on search work per question.")
    query_cache_size: int = Field(default=128, ge=0)

    # Fusion, expansion and reranking (every default preserves v0.1 behaviour; see docs/RETRIEVAL.md for the ablation)
    fusion_strategy: str = Field(default="rrf", description="rrf (equal weights) | weighted_rrf (uses fusion_weights) | linear.")
    fusion_weights: dict[str, float] = Field(default_factory=lambda: {"bm25": 1.0, "vector": 1.0, "entity": 1.0, "exact": 1.0})
    fusion_retrievers: list[str] = Field(default_factory=lambda: ["bm25", "vector"], description="Retrievers fused by the hybrid strategy: bm25, vector, entity, exact.")
    query_expansion: bool = Field(default=False, description="Also retrieve with deterministic query variants (original kept first).")
    expansion_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    query_rewrite_llm: bool = Field(default=False, description="Add validated LLM paraphrases (needs a chat provider).")
    predicate_hints: bool = Field(default=True, description='Map phrasings like "how much ... make" to the salary attribute for fact lookup.')
    rerank: str = Field(default="off", description="off | on. Reorders the fused top candidates with the configured reranker.")
    rerank_top_n: int = Field(default=20, ge=2, le=200)

    # Ingestion
    extraction_mode: str = Field(default="rules", description="rules (offline, default) | llm (LLM, rules fallback) | hybrid (both).")
    extraction_strict: bool = Field(default=True, description="Require a lexical cue for the predicate inside the cited span.")
    chunk_chars: int = Field(default=800, ge=100)
    chunk_overlap: int = Field(default=100, ge=0)
    redact_secrets: bool = True
    near_duplicate_cosine: float = Field(default=0.92, ge=0.0, le=1.0)
    near_duplicate_jaccard: float = Field(default=0.8, ge=0.0, le=1.0)

    # Consolidation
    cluster_min_size: int = Field(default=3, ge=2)
    cluster_cosine: float = Field(default=0.35, ge=0.0, le=1.0)

    # Routing / learning
    cost_tolerance: float = Field(default=0.1, ge=0.0, le=1.0, description="Score gap within which cheaper strategies win.")
    low_route_confidence: float = Field(default=0.25, ge=0.0, le=1.0)
    adaptive_learning: bool = Field(default=False, description="Let feedback statistics override default routing.")
    learning_min_samples: int = Field(default=20, ge=5)

    # Embeddings
    vector_index: str = Field(default="exact", description="exact (brute-force cosine, default) | ivf (approximate inverted-file index, see docs/SCALING.md).")
    ann_min_vectors: int = Field(default=20000, ge=100, description="The ivf index is used only once a scope holds at least this many vectors.")
    ann_nprobe: int = Field(default=8, ge=1, le=256, description="Clusters scored per query; higher is slower and closer to exact.")
    embedding_dim: int = Field(default=512, ge=32)
    embedding_on_mismatch: str = Field(default="error", description="error | reindex when a model's vector size changes under the same name.")

    @field_validator("fusion_strategy")
    @classmethod
    def _fusion_known(cls, v: str) -> str:
        if v not in ("rrf", "weighted_rrf", "linear"):
            raise ValueError("fusion_strategy must be rrf, weighted_rrf or linear")
        return v

    @field_validator("fusion_retrievers")
    @classmethod
    def _retrievers_known(cls, v: list[str]) -> list[str]:
        bad = set(v) - {"bm25", "vector", "entity", "exact"}
        if bad or not v:
            raise ValueError(f"fusion_retrievers must be a non-empty subset of bm25, vector, entity, exact (got {sorted(bad) or 'empty'})")
        return list(dict.fromkeys(v))

    @field_validator("fusion_weights")
    @classmethod
    def _weights_positive(cls, v: dict[str, float]) -> dict[str, float]:
        if any(w < 0 for w in v.values()):
            raise ValueError("fusion_weights must be non-negative")
        return v

    @field_validator("rerank")
    @classmethod
    def _rerank_known(cls, v: str) -> str:
        if v not in ("off", "on"):
            raise ValueError("rerank must be 'off' or 'on'")
        return v

    @field_validator("embedding_on_mismatch")
    @classmethod
    def _mismatch_known(cls, v: str) -> str:
        if v not in ("error", "reindex"):
            raise ValueError("embedding_on_mismatch must be 'error' or 'reindex'")
        return v

    @field_validator("vector_index")
    @classmethod
    def _vindex_known(cls, v: str) -> str:
        if v not in ("exact", "ivf"):
            raise ValueError("vector_index must be 'exact' or 'ivf'")
        return v

    @field_validator("extraction_mode")
    @classmethod
    def _mode_known(cls, v: str) -> str:
        if v not in ("rules", "llm", "hybrid"):
            raise ValueError("extraction_mode must be rules, llm or hybrid")
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_smaller(cls, v: int, info) -> int:
        chunk = info.data.get("chunk_chars", 800)
        if v >= chunk:
            raise ValueError("chunk_overlap must be smaller than chunk_chars")
        return v

    @field_validator("answerability")
    @classmethod
    def _policy_known(cls, v: str) -> str:
        if v not in ANSWERABILITY_POLICIES:
            raise ValueError(f"answerability must be one of {', '.join(ANSWERABILITY_POLICIES)}")
        return v

    @property
    def section_support(self) -> float | None:
        """Section-level support threshold in force: the explicit override, else the policy's value (None = off)."""
        if self.memory_support_coverage is not None:
            return self.memory_support_coverage
        return ANSWERABILITY_POLICIES[self.answerability][0]

    @property
    def semantic_threshold(self) -> float | None:
        """Cosine a best sentence needs to support an answer when a neural embedder is configured (None = off)."""
        if self.semantic_support is not None:
            return self.semantic_support
        return ANSWERABILITY_POLICIES[self.answerability][1]

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / self.db_filename
