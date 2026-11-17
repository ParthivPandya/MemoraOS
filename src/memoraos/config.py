"""Runtime configuration with validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    """All tunables in one validated place. Every value has a documented reason."""

    data_dir: Path = Field(default=Path("./.memoraos"), description="Directory for the SQLite file and source copies.")
    db_filename: str = "memoraos.db"

    # Retrieval
    default_top_k: int = Field(default=5, ge=1, le=200)
    candidate_pool: int = Field(default=50, ge=5, le=1000, description="Candidates per retriever before fusion.")
    rrf_k: int = Field(default=60, ge=1, description="Reciprocal-rank-fusion constant from Cormack et al. (2009).")
    min_evidence_coverage: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Fraction of query terms the evidence must cover to answer."
    )
    max_graph_hops: int = Field(default=6, ge=1, le=8)
    query_cache_size: int = Field(default=128, ge=0)

    # Ingestion
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
    embedding_dim: int = Field(default=512, ge=32)

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_smaller(cls, v: int, info) -> int:
        chunk = info.data.get("chunk_chars", 800)
        if v >= chunk:
            raise ValueError("chunk_overlap must be smaller than chunk_chars")
        return v

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / self.db_filename
