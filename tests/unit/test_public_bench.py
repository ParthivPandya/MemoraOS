from benchmarks.public import Retrievers, Unit, _distinct, _paired, score


def test_distinct_keeps_rank_order_and_drops_blanks():
    assert _distinct(["a", "", "b", "a", "c"], 2) == ["a", "b"]


def test_score_and_paired_counts():
    hits = {"x": {5: [True, True, False, False]}, "y": {5: [True, False, True, False]}}
    row = score(hits)["x"]["hit@5"]
    assert (row["hits"], row["n"], row["rate"]) == (2, 4, 0.5)
    assert _paired(hits, "x", "y", 5) == {"a": "x", "b": "y", "k": 5, "a_only": 1, "b_only": 1}


def test_all_systems_rank_the_matching_unit_first():
    units = [Unit("u1", "The deployment region is Frankfurt."), Unit("u2", "Birthday cake needs three eggs and flour.")]
    r = Retrievers(units)
    try:
        for system in ("bm25", "vector", "hybrid_rag", "memoraos_retriever"):
            assert r.search(system, "Which region is the deployment in?", 1) == ["u1"], system
    finally:
        r.close()
