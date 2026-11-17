"""Regression guards: coarse performance budgets and benchmark determinism.

Budgets are deliberately generous (CI hardware varies); they catch accidental order-of-magnitude regressions,
not small drifts. Real measurements live in benchmarks/reports.
"""

import time

from memoraos import MemoryOS


def test_ingest_and_recall_scale_budget():
    m = MemoryOS.in_memory()
    t0 = time.perf_counter()
    for i in range(300):
        m.remember(f"Person{i} lives in City{i % 40}. Person{i} works at Company{i % 25}.", user_id="u")
    ingest = time.perf_counter() - t0
    t0 = time.perf_counter()
    for i in range(0, 300, 10):
        res = m.recall(f"Where does Person{i} live?", user_id="u", use_cache=False)
        assert f"City{i % 40}" in res.answer
    per_query_ms = (time.perf_counter() - t0) / 30 * 1000
    assert ingest < 60 and per_query_ms < 250, (ingest, per_query_ms)


def test_embedding_cache_prevents_re_embedding(mem):
    calls = []
    orig = mem.embedder.embed
    mem.embedder.embed = lambda texts: (calls.append(len(texts)), orig(texts))[1]
    mem.store.embedder = mem.embedder
    mem.remember("Alice leads Project Atlas.", user_id="u")
    mem.remember("Alice leads Project Atlas.", user_id="other")  # same text, different user
    assert sum(calls) == 1


def test_benchmark_dataset_is_deterministic():
    from benchmarks.datasets import build_dataset, dataset_hash

    assert dataset_hash(build_dataset(7, 0.34)) == dataset_hash(build_dataset(7, 0.34))
    assert dataset_hash(build_dataset(7, 0.34)) != dataset_hash(build_dataset(8, 0.34))


def test_benchmark_result_digest_is_reproducible(tmp_path):
    import json

    from benchmarks.run import main

    digests = []
    for i in range(2):
        main(["--seed", "3", "--quick", "--scenarios", "temporal_reasoning", "contradiction_resolution", "--no-ablation", "--out", str(tmp_path / str(i))])
        digests.append(json.loads((tmp_path / str(i) / "benchmark_results.json").read_text())["deterministic_digest"])
    assert digests[0] == digests[1]


def test_memoraos_beats_plain_hybrid_on_temporal_and_conflict_cases():
    """Guards the headline mechanism (not a marketing number): see benchmarks/reports for full results."""
    import json
    import tempfile

    from benchmarks.run import main

    with tempfile.TemporaryDirectory() as d:
        main(["--seed", "5", "--quick", "--scenarios", "temporal_reasoning", "contradiction_resolution", "--no-ablation", "--out", d])
        m = json.loads(open(f"{d}/benchmark_results.json", encoding="utf-8").read())["metrics"]
    for sc in ("temporal_reasoning", "contradiction_resolution"):
        assert m["memoraos"]["scenarios"][sc]["accuracy"] > m["hybrid_rag"]["scenarios"][sc]["accuracy"] + 0.3
