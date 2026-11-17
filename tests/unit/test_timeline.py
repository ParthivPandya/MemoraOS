from memoraos.models import Fact
from memoraos.truth.timeline import build_timeline


def f(obj, *, valid_from=None, until=None, rec="2026-01-01T00:00:00.000000Z", src="document", rel=0.7, mem="m1", slot="database", fid=None):
    return Fact(
        id=fid or f"{mem}-{obj}", memory_id=mem, subject="Atlas", predicate="database", object=obj, subject_key="atlas", object_key=obj.lower(),
        slot=slot, valid_from=valid_from, valid_until=until, recorded_at=rec, extraction_confidence=0.9, source_reliability=rel, source_type=src,
    )


def test_explicit_dates_order_values_regardless_of_ingestion_order():
    tl = build_timeline([f("B", valid_from="2025-01-01T00:00:00.000000Z", rec="2026-01-02T00:00:00.000000Z"), f("A", valid_from="2024-01-01T00:00:00.000000Z", rec="2026-01-03T00:00:00.000000Z")])
    assert [r.value for r in tl.at("2026-06-01T00:00:00.000000Z")[0]] == ["B"]
    assert [r.value for r in tl.at("2024-06-01T00:00:00.000000Z")[0]] == ["A"]
    assert tl.at("2023-01-01T00:00:00.000000Z") is None
    assert tl.contradictions == []


def test_same_effective_date_is_conflict():
    tl = build_timeline([f("A", valid_from="2025-01-01T00:00:00.000000Z"), f("B", valid_from="2025-01-01T00:00:00.000000Z", rec="2026-01-02T00:00:00.000000Z")])
    runs, conflicted = tl.at("2025-06-01T00:00:00.000000Z")
    assert conflicted and {r.value for r in runs} == {"A", "B"}
    assert tl.contradictions[0].kind == "conflict" and not tl.contradictions[0].resolved


def test_undated_equal_reliability_documents_conflict_until_a_later_update():
    a, b = f("A", rec="2026-01-01T00:00:00.000000Z"), f("B", rec="2026-01-02T00:00:00.000000Z")
    assert build_timeline([a, b]).contradictions[0].resolved is False
    c = f("C", valid_from="2026-02-01T00:00:00.000000Z", rec="2026-01-03T00:00:00.000000Z")
    tl = build_timeline([a, b, c])
    assert [r.value for r in tl.at("2026-03-01T00:00:00.000000Z")[0]] == ["C"]
    assert tl.contradictions[0].resolved  # the old conflict is closed, but still reported


def test_self_reported_later_statement_supersedes():
    tl = build_timeline([f("A", src="user_statement", rel=0.9), f("B", src="user_statement", rel=0.9, rec="2026-01-02T00:00:00.000000Z")])
    assert [r.value for r in tl.at("2026-06-01T00:00:00.000000Z")[0]] == ["B"] and tl.contradictions == []


def test_reliability_margin_and_rejection_of_weaker_later_value():
    strong_first = build_timeline([f("A", rel=0.9), f("B", rel=0.4, rec="2026-01-02T00:00:00.000000Z", src="inferred")])
    assert [r.value for r in strong_first.at("2026-06-01T00:00:00.000000Z")[0]] == ["A"]
    assert strong_first.contradictions[0].kind == "resolved_by_reliability" and strong_first.rejected
    strong_later = build_timeline([f("A", rel=0.4, src="inferred"), f("B", rel=0.9, rec="2026-01-02T00:00:00.000000Z")])
    assert [r.value for r in strong_later.at("2026-06-01T00:00:00.000000Z")[0]] == ["B"]


def test_version_change_detection_and_repeated_assertions_merge():
    facts = [f("Angular 16", slot="uses:angular"), f("Angular 16", slot="uses:angular", mem="m2", rec="2026-01-02T00:00:00.000000Z"), f("Angular 19", slot="uses:angular", rec="2026-01-03T00:00:00.000000Z", mem="m3")]
    tl = build_timeline(facts)
    assert tl.contradictions[0].kind == "possible_version_change" and tl.contradictions[0].resolved
    assert len(tl.groups) == 2 and tl.groups[0].runs[0].memory_ids == ["m1", "m2"]


def test_equal_timestamps_keep_insertion_order():
    """Regression (found by CI on Windows): identical recorded_at must not let random ids pick the latest."""
    same = "2026-01-01T00:00:00.000000Z"
    for _ in range(20):
        facts = [f("Angular 16", slot="uses:angular", mem="m1", rec=same, fid="zzz-first"), f("Angular 19", slot="uses:angular", mem="m2", rec=same, fid="aaa-second")]
        tl = build_timeline(facts)
        assert [r.value for r in tl.at("2026-06-01T00:00:00.000000Z")[0]] == ["Angular 19"]


def test_explicit_until_ends_a_value():
    tl = build_timeline([f("A", valid_from="2024-01-01T00:00:00.000000Z", until="2024-12-31T00:00:00.000000Z")])
    assert tl.at("2024-06-01T00:00:00.000000Z") is not None and tl.at("2025-06-01T00:00:00.000000Z") is None
