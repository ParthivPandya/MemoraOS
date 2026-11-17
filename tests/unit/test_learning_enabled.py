def test_enabled_learning_runs_end_to_end_and_only_overrides_with_evidence():
    from memoraos import MemoryOS, Settings

    m = MemoryOS.in_memory(settings=Settings(adaptive_learning=True, learning_min_samples=5))
    m.remember("Zephyr runs a nightly rollup job for the platform.", user_id="u")
    for _ in range(3):
        res = m.recall("tell me about the nightly rollup", user_id="u", use_cache=False)
        m.feedback(res.recall_id, correct=True)
    assert not res.plan.learned_override  # too few labelled samples per strategy to override anything
    assert res.supported
