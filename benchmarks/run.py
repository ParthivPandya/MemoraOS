"""Benchmark runner: python -m benchmarks.run [--seeds 7 8 9] [--quick] [--out benchmarks/reports]"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import random
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from memoraos.evaluation.metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k

from .datasets import V02_SCENARIOS, Scenario, build_dataset, dataset_hash
from .report import render_markdown
from .systems import EXTERNAL, TOP_K, MemoraSystem, System, available_systems

BOOTSTRAP = 1000


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _contains(answer: str, value: str) -> bool:
    return _norm(value) in _norm(answer)


def judge(q, resp) -> dict:
    """Score one response. All rules are mechanical string/ID checks; there is no LLM judge."""
    row: dict = {"qid": q.qid, "scenario": q.scenario, "kind": q.kind, "answerable": q.answerable, "tag": q.tag, "strategy": resp.strategy}
    ranked = resp.evidence_events
    rel = set(q.relevant)
    if q.kind == "conflict":
        row["correct"] = bool(resp.flagged_conflict)
        row["flagged"], row["expected_conflict"] = bool(resp.flagged_conflict), True
    elif not q.answerable:
        row["correct"] = not resp.supported
        row["unsupported_answer"] = bool(resp.supported)
    else:
        ok = resp.supported and all(_contains(resp.answer, g) for g in q.gold) and not any(_contains(resp.answer, w) for w in q.wrong if not any(_norm(w) in _norm(g) for g in q.gold))
        if q.kind == "update_no_conflict":
            ok = ok and not resp.flagged_conflict
            row["flagged"], row["expected_conflict"] = bool(resp.flagged_conflict), False
        row["correct"] = bool(ok)
        row["false_abstain"] = not resp.supported
        if rel:
            row.update(recall=recall_at_k(ranked, rel, TOP_K), precision=precision_at_k(ranked, rel, TOP_K), mrr=mrr(ranked, rel), ndcg=ndcg_at_k(ranked, rel, TOP_K), evidence_hit=float(bool(set(ranked[:TOP_K]) & rel)))
            if q.scenario == "evidence_attribution":
                row["citation_exact"] = float(bool(ranked) and ranked[0] in rel and bool(resp.excerpts) and all(_contains(resp.excerpts[0], g) for g in q.gold))
    row["context_tokens"] = resp.context_tokens
    row["latency_ms"] = resp.latency_ms
    return row


def run_scenario(sc: Scenario, system: System, out: dict) -> None:
    events = sorted(sc.events, key=lambda e: e.idx)
    total_bytes = sum(len(e.text.encode()) for e in events)
    applied = 0
    ingest_s = 0.0
    results: list[dict] = []
    questions = sorted(sc.questions, key=lambda q: (q.after_event if q.after_event is not None else len(events)))
    extra: dict = {}

    def ask_all(qs, phase: str) -> None:
        for q in qs:
            r = judge(q, system.ask(q))
            r["phase"] = phase
            results.append(r)

    if any(q.after_event is not None for q in questions):
        for q in questions:
            target = q.after_event if q.after_event is not None else len(events)
            if target > applied:
                ingest_s += system.ingest(events[applied:target])
                applied = target
            r = judge(q, system.ask(q))
            r["phase"] = "final"
            results.append(r)
    else:
        ingest_s += system.ingest(events)
        if sc.restart:
            ask_all(questions, "before_restart")
            extra["restart_seconds"] = system.restart()
            ask_all(questions, "final")
        elif sc.consolidate:
            ask_all(questions, "before_consolidation")
            if isinstance(system, MemoraSystem):
                rep = system.consolidate(events[0].user)
                extra["consolidation_created_summaries"] = len(rep["created_memory_ids"])
                extra["originals_modified"] = rep["originals_modified"]
                # every original memory must still be retrievable, byte for byte
                intact = 0
                for idx, mid in system.event_to_mem.items():
                    rec = system.eng.get(mid, user_id=events[0].user, tenant_id="bench")
                    intact += int(rec.original_content == next(e.text for e in events if e.idx == idx))
                extra["originals_intact"] = intact / max(1, len(system.event_to_mem))
            ask_all(questions, "final")
        else:
            ask_all(questions, "final")
    extra["ingest_seconds"] = ingest_s
    extra["ingest_ms_per_event"] = 1000 * ingest_s / max(1, len(events))
    extra["storage_bytes"] = system.storage_bytes()
    extra["raw_text_bytes"] = total_bytes
    out.setdefault(system.name, {})[sc.name] = {"results": results, "extra": extra}


def hardware() -> dict:
    info = {
        "platform": platform.platform(), "processor": platform.processor(), "machine": platform.machine(), "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0], "numpy": np.__version__, "sqlite": sqlite3.sqlite_version,
    }
    try:
        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]

        m = _MS()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
        info["ram_gb"] = round(m.ullTotalPhys / 2**30, 1)
    except Exception:  # noqa: BLE001 - RAM is optional metadata
        try:
            info["ram_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
        except (ValueError, OSError, AttributeError):
            info["ram_gb"] = None
    return info


def bootstrap_ci(values: list[float], seed: int = 12345) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP))
    return means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]


def percentile(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))] if s else 0.0


def aggregate(raw: dict[str, dict[str, list[dict]]], extras: dict[str, dict[str, list[dict]]]) -> dict:
    """raw[system][scenario] -> pooled question rows over seeds"""
    out: dict = {}
    for system, scen in raw.items():
        out[system] = {"scenarios": {}}
        accs = []
        for name, rows in scen.items():
            final = [r for r in rows if r["phase"] == "final"]
            m: dict = {"n": len(final), "accuracy": statistics.fmean(float(r["correct"]) for r in final) if final else 0.0}
            lo, hi = bootstrap_ci([float(r["correct"]) for r in final])
            m["accuracy_ci95"] = [round(lo, 4), round(hi, 4)]
            ans = [r for r in final if r["answerable"] and r["kind"] != "conflict"]
            for key in ("recall", "precision", "mrr", "ndcg", "evidence_hit", "citation_exact"):
                vals = [r[key] for r in ans if key in r]
                if vals:
                    m[{"recall": "recall_at_5", "precision": "precision_at_5", "mrr": "mrr", "ndcg": "ndcg_at_5", "evidence_hit": "evidence_coverage", "citation_exact": "citation_exact_top1"}[key]] = statistics.fmean(vals)
            un = [r for r in final if not r["answerable"]]
            if un:
                m["unsupported_answer_rate"] = statistics.fmean(float(r["unsupported_answer"]) for r in un if "unsupported_answer" in r)
            if ans:
                m["false_abstain_rate"] = statistics.fmean(float(r["false_abstain"]) for r in ans)
            cd = [r for r in final if "expected_conflict" in r]
            if cd:
                m["contradiction_detection_accuracy"] = statistics.fmean(float(r["flagged"] == r["expected_conflict"]) for r in cd)
            m["mean_context_tokens"] = statistics.fmean(r["context_tokens"] for r in final) if final else 0.0
            m["latency_ms_p50"] = percentile([r["latency_ms"] for r in final], 0.5)
            m["latency_ms_p95"] = percentile([r["latency_ms"] for r in final], 0.95)
            tags = defaultdict(list)
            for r in final:
                if r["tag"]:
                    tags[r["tag"]].append(float(r["correct"]))
            if tags:
                m["accuracy_by_tag"] = {t: statistics.fmean(v) for t, v in sorted(tags.items())}
            ex = extras[system][name]
            m["ingest_ms_per_event"] = statistics.fmean(e["ingest_ms_per_event"] for e in ex)
            m["storage_overhead_ratio"] = statistics.fmean(e["storage_bytes"] / max(1, e["raw_text_bytes"]) for e in ex)
            for k in ("restart_seconds", "originals_intact", "consolidation_created_summaries", "originals_modified"):
                vals = [e[k] for e in ex if k in e]
                if vals:
                    m[k] = statistics.fmean(vals)
            before = [r for r in rows if r["phase"] in ("before_restart", "before_consolidation")]
            if before:
                m["accuracy_before"] = statistics.fmean(float(r["correct"]) for r in before)
            out[system]["scenarios"][name] = m
            accs.append(m["accuracy"])
        out[system]["macro_accuracy"] = statistics.fmean(accs) if accs else 0.0
        pooled = [float(r["correct"]) for rows in scen.values() for r in rows if r["phase"] == "final"]
        lo, hi = bootstrap_ci(pooled)
        out[system]["pooled_accuracy"] = statistics.fmean(pooled) if pooled else 0.0
        out[system]["pooled_accuracy_ci95"] = [round(lo, 4), round(hi, 4)]
        # the v0.1 suite keeps its original definition, so its headline stays comparable across releases
        for key, keep in (("v01_suite", lambda n: n not in V02_SCENARIOS), ("v02_scenarios", lambda n: n in V02_SCENARIOS)):
            part = [float(r["correct"]) for n, rows in scen.items() if keep(n) for r in rows if r["phase"] == "final"]
            if part:
                plo, phi = bootstrap_ci(part)
                out[system][f"pooled_accuracy_{key}"] = statistics.fmean(part)
                out[system][f"pooled_accuracy_{key}_ci95"] = [round(plo, 4), round(phi, 4)]
    return out


def strip_timing(obj):
    if isinstance(obj, dict):
        return {k: strip_timing(v) for k, v in obj.items() if not (k.startswith("latency") or "seconds" in k or "ms_per" in k)}
    if isinstance(obj, list):
        return [strip_timing(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MemoraOS Memory Benchmark Lab")
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 8, 9])
    ap.add_argument("--seed", type=int, help="single seed shortcut")
    ap.add_argument("--quick", action="store_true", help="1/3-size datasets")
    ap.add_argument("--out", default="benchmarks/reports")
    ap.add_argument("--scenarios", nargs="*", help="subset of scenario names")
    ap.add_argument("--no-ablation", action="store_true")
    args = ap.parse_args(argv)
    seeds = [args.seed] if args.seed is not None else args.seeds
    scale = 0.34 if args.quick else 1.0
    t_start = time.perf_counter()

    raw: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    extras: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    hashes = {}
    n_questions = 0
    for seed in seeds:
        ds = build_dataset(seed, scale)
        hashes[str(seed)] = dataset_hash(ds)
        for name, sc in ds.items():
            if args.scenarios and name not in args.scenarios:
                continue
            n_questions += len(sc.questions)
            for system in available_systems(not args.no_ablation):
                collected: dict = {}
                try:
                    run_scenario(sc, system, collected)
                finally:
                    system.close()
                for sname, per in collected.items():
                    raw[sname][name].extend(per[name]["results"])
                    extras[sname][name].append(per[name]["extra"])
            print(f"seed {seed}: {name:32s} done", flush=True)
    metrics = aggregate(raw, extras)
    degradation = {}
    for system, scen in raw.items():
        rows = [r for r in scen.get("degradation_after_updates", []) if r["phase"] == "final"]
        by = defaultdict(list)
        for r in rows:
            by[r["tag"]].append(float(r["correct"]))
        degradation[system] = {t: statistics.fmean(v) for t, v in sorted(by.items(), key=lambda kv: int(kv[0].split("_")[1]))}
    systems_meta = [{"name": s.name, "description": s.description} for s in available_systems(not args.no_ablation)]
    for s in available_systems(not args.no_ablation):
        s.close()
    report = {
        "benchmark": "MemoraOS Memory Benchmark Lab", "version": 1,
        "command": "python -m benchmarks.run " + " ".join(argv if argv is not None else sys.argv[1:]),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": hardware(),
        "configuration": {"seeds": seeds, "scale": scale, "top_k": TOP_K, "embedder": "HashingEmbedder(512) (lexical feature hashing; no neural model)", "llm_used": False, "bootstrap_resamples": BOOTSTRAP, "dataset_sha256": hashes, "questions_per_seed_approx": n_questions // max(1, len(seeds))},
        "systems": systems_meta,
        "external_systems": [p.probe() for p in EXTERNAL],
        "metrics": metrics,
        "degradation_curve": degradation,
        "wall_clock_seconds": round(time.perf_counter() - t_start, 1),
    }
    report["deterministic_digest"] = hashlib.sha256(json.dumps(strip_timing({"c": report["configuration"], "m": metrics, "d": degradation}), sort_keys=True).encode()).hexdigest()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "REPORT.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {out / 'benchmark_results.json'} and REPORT.md  (digest {report['deterministic_digest'][:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
