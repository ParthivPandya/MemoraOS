"""Retrieval ablations: does each v0.2 component help, hurt, or do nothing on the benchmark?

    python -m benchmarks.ablations [--seeds 7 8 9] [--out benchmarks/reports]

Each variant runs the SAME datasets as the main benchmark. Retrieval variants force the ``hybrid`` strategy so the
fact engine cannot mask their effect; pipeline variants run the full router. Results are written to
``ablation_v02.json`` / ``ABLATION_V02.md`` and decide the shipped defaults (see docs/RETRIEVAL.md): a component only
becomes a default if it does not regress any scenario.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from memoraos.config import Settings
from memoraos.providers.local import LexicalReranker

from .datasets import V02_SCENARIOS, build_dataset
from .run import run_scenario
from .systems import MemoraSystem, System


def variants() -> list[tuple[str, str, dict, str | None, bool]]:
    """(label, description, settings overrides, forced strategy, needs reranker)"""
    h = "hybrid"
    return [
        ("hybrid:bm25+vector", "forced hybrid, default retrievers (v0.1 behaviour)", {}, h, False),
        ("hybrid:+entity", "forced hybrid, adds the entity retriever", {"fusion_retrievers": ["bm25", "vector", "entity"]}, h, False),
        ("hybrid:+exact", "forced hybrid, adds the exact-identifier/value retriever", {"fusion_retrievers": ["bm25", "vector", "exact"]}, h, False),
        ("hybrid:+entity+exact", "forced hybrid, adds both", {"fusion_retrievers": ["bm25", "vector", "entity", "exact"]}, h, False),
        ("hybrid:weighted_rrf(bm25x2)", "forced hybrid, weighted RRF with BM25 weight 2", {"fusion_strategy": "weighted_rrf", "fusion_weights": {"bm25": 2.0, "vector": 1.0}}, h, False),
        ("hybrid:linear", "forced hybrid, min-max linear score fusion", {"fusion_strategy": "linear"}, h, False),
        ("hybrid:+expansion", "forced hybrid, deterministic query expansion", {"query_expansion": True}, h, False),
        ("hybrid:+rerank(lexical)", "forced hybrid, lexical-coverage reranker over the top 20", {"rerank": "on"}, h, True),
        ("full:default", "full pipeline, shipped defaults", {}, None, False),
        ("full:no_evidence_fusion", "full pipeline with evidence fusion disabled", {"evidence_fusion": False}, None, False),
        ("full:no_predicate_hints", "full pipeline without predicate hints", {"predicate_hints": False}, None, False),
        ("full:+expansion", "full pipeline with query expansion", {"query_expansion": True}, None, False),
        ("full:+entity+exact", "full pipeline, hybrid also fuses entity + exact retrievers", {"fusion_retrievers": ["bm25", "vector", "entity", "exact"]}, None, False),
        ("full:+rerank(lexical)", "full pipeline with the lexical reranker", {"rerank": "on"}, None, True),
        ("full:linear", "full pipeline with min-max linear score fusion", {"fusion_strategy": "linear"}, None, False),
        ("full:answer_1sent", "full pipeline with answer_max_sentences=1 (v0.1 answer composition)", {"answer_max_sentences": 1}, None, False),
        ("full:head_guard_always", "full pipeline with head_guard_coverage=1.01 (attribute word always required, v0.1)", {"head_guard_coverage": 1.01}, None, False),
        ("full:v01_answering", "full pipeline with both v0.1 answer-composition behaviours", {"answer_max_sentences": 1, "head_guard_coverage": 1.01}, None, False),
    ]


def make_system(label: str, desc: str, overrides: dict, force: str | None, rerank: bool) -> System:
    return MemoraSystem(force_strategy=force, label=label, settings=Settings(**overrides), reranker=LexicalReranker() if rerank else None, description=desc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MemoraOS v0.2 retrieval ablations")
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 8, 9])
    ap.add_argument("--out", default="benchmarks/reports")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    rows: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    quality: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    desc = {}
    for seed in args.seeds:
        ds = build_dataset(seed, 1.0)
        for name, sc in ds.items():
            for spec in variants():
                system = make_system(*spec)
                desc[spec[0]] = spec[1]
                collected: dict = {}
                try:
                    run_scenario(sc, system, collected)
                finally:
                    system.close()
                res = [r for r in collected[system.name][name]["results"] if r["phase"] == "final"]
                rows[spec[0]][name].extend(float(r["correct"]) for r in res)
                for key in ("mrr", "recall"):
                    quality[spec[0]][key].extend(r[key] for r in res if key in r)
            print(f"seed {seed}: {name:32s} done", flush=True)
    scenarios = list(next(iter(rows.values())))
    table = {}
    for label, per in rows.items():
        pooled = [v for vals in per.values() for v in vals]
        table[label] = {
            "description": desc[label],
            "pooled_accuracy": statistics.fmean(pooled),
            "pooled_accuracy_v01_suite": statistics.fmean([v for n, vals in per.items() if n not in V02_SCENARIOS for v in vals]),
            "mrr": statistics.fmean(quality[label]["mrr"]) if quality[label]["mrr"] else None,
            "recall_at_5": statistics.fmean(quality[label]["recall"]) if quality[label]["recall"] else None,
            "by_scenario": {n: statistics.fmean(vals) for n, vals in per.items()},
        }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "benchmark": "MemoraOS v0.2 retrieval ablations", "command": "python -m benchmarks.ablations " + " ".join(argv if argv is not None else sys.argv[1:]),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": args.seeds, "scenarios": scenarios,
        "variants": table, "wall_clock_seconds": round(time.perf_counter() - t0, 1),
    }
    (out / "ablation_v02.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "ABLATION_V02.md").write_text(render(report), encoding="utf-8")
    print(f"wrote {out / 'ablation_v02.json'}")
    return 0


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def render(rep: dict) -> str:
    v = rep["variants"]
    scen = rep["scenarios"]
    L = ["# v0.2 retrieval ablations\n", "_Generated by `python -m benchmarks.ablations`; every number comes from `ablation_v02.json`._\n"]
    L.append(f"- Command: `{rep['command']}`; seeds {rep['seeds']}; wall clock {rep['wall_clock_seconds']} s")
    L.append("- `hybrid:*` variants force the plain hybrid strategy (no fact engine) to isolate retrieval; `full:*` variants run the whole router.")
    L.append("- A variant is only adopted as a default when it does not lower any scenario's accuracy against its baseline row (`hybrid:bm25+vector` or `full:default`).\n")
    L.append("| Variant | Pooled | v0.1 suite | MRR | Recall@5 | What changed |")
    L.append("|---|---|---|---|---|---|")
    for k, d in v.items():
        L.append(f"| `{k}` | {_pct(d['pooled_accuracy'])} | {_pct(d['pooled_accuracy_v01_suite'])} | {_pct(d['mrr'])} | {_pct(d['recall_at_5'])} | {d['description']} |")
    L.append("\n## Per-scenario accuracy\n")
    L.append("| Scenario | " + " | ".join(f"`{k}`" for k in v) + " |")
    L.append("|---|" + "|".join("---" for _ in v) + "|")
    for s in scen:
        L.append(f"| {s} | " + " | ".join(_pct(d["by_scenario"][s]) for d in v.values()) + " |")
    L.append("\n## Regressions against the baseline row\n")
    for k, d in v.items():
        base = v["hybrid:bm25+vector"] if k.startswith("hybrid:") else v["full:default"]
        if base is d:
            continue
        worse = [(s, base["by_scenario"][s], d["by_scenario"][s]) for s in scen if d["by_scenario"][s] < base["by_scenario"][s] - 1e-9]
        better = [(s, base["by_scenario"][s], d["by_scenario"][s]) for s in scen if d["by_scenario"][s] > base["by_scenario"][s] + 1e-9]
        L.append(f"- `{k}`: " + ("no regressions" if not worse else "regresses " + ", ".join(f"{s} {_pct(a)}→{_pct(b)}" for s, a, b in worse)) + ("; improves " + ", ".join(f"{s} {_pct(a)}→{_pct(b)}" for s, a, b in better) if better else ""))
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
