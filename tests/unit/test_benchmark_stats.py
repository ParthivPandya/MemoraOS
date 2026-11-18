from benchmarks.stats import brier, ece, overlaps, wilson


def test_wilson_never_collapses_to_a_point_for_a_perfect_small_sample():
    lo, hi = wilson(21, 21)
    assert hi == 1.0 and 0.84 < lo < 0.86  # 21 of 21 still allows a true rate near 85%
    lo0, hi0 = wilson(0, 10)
    assert lo0 == 0.0 and 0.25 < hi0 < 0.31
    assert wilson(0, 0) == (0.0, 1.0)


def test_brier_and_ece_on_known_values():
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert brier([0.5, 0.5], [True, False]) == 0.25
    assert brier([], []) is None
    assert ece([0.9] * 10, [True] * 9 + [False]) == 0.0  # confidence equals accuracy
    assert abs(ece([0.9] * 10, [True] * 5 + [False] * 5) - 0.4) < 1e-9


def test_interval_overlap():
    assert overlaps((0.1, 0.5), (0.4, 0.9)) and not overlaps((0.1, 0.3), (0.4, 0.9))
