from __future__ import annotations

import numpy as np

from memoraos import MemoryOS
from memoraos.config import Settings
from memoraos.providers.local import HashingEmbedder
from memoraos.retrieval.ann import IVFIndex, measure_recall

TEXTS = [
    "The deployment pipeline runs unit tests before every release candidate.",
    "Invoices are archived for seven years in the finance bucket.",
    "The on-call engineer rotates every Monday at nine in the morning.",
    "Customer support tickets are triaged within four business hours.",
    "The staging cluster is rebuilt from scratch every Sunday night.",
    "Quarterly security reviews cover dependency updates and access logs.",
    "The design system exposes colour tokens as CSS custom properties.",
    "Database migrations are applied by a dedicated release job.",
] * 30


def _matrix(n_extra: int = 0) -> np.ndarray:
    emb = HashingEmbedder(128)
    texts = [f"{t} Variant {i}." for i, t in enumerate(TEXTS)]
    return np.asarray(emb.embed(texts[: len(texts) - n_extra]), dtype=np.float32)


def test_probing_every_list_is_exact():
    mat = _matrix()
    res = measure_recall(mat, mat[:20], 10, nlist=8, nprobe=8)
    assert res["recall_at_k"] == 1.0 and res["scored_fraction"] == 1.0


def test_results_are_sorted_and_deterministic():
    mat = _matrix()
    a = IVFIndex(mat, nlist=8, nprobe=3, seed=1).search(mat[5], 5)
    b = IVFIndex(mat, nlist=8, nprobe=3, seed=1).search(mat[5], 5)
    assert a[0].tolist() == b[0].tolist() and list(a[1]) == sorted(a[1], reverse=True)


def test_engine_can_route_vector_search_through_the_ivf_index():
    s = Settings(vector_index="ivf", ann_min_vectors=100, ann_nprobe=256, embedding_dim=128)
    with MemoryOS.in_memory(settings=s) as m:
        for i, t in enumerate(TEXTS[:120]):
            m.remember(f"{t} Variant {i}.", user_id="u", source_type="document")
        hits = m.vectors.search(m.scope_for("u"), "Invoices are archived for seven years", 3)
        assert hits and m.vectors._ann
