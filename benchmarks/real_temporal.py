"""Real temporal benchmark: "what was the latest version on date D?" over the dated CPython release history.

The records are copied from PEP 693, 719 and 745 (data/python_releases.json). Nothing is generated: every gold
answer is computed from those real dates by the rules below, and every question is built from them.

* Each record becomes one sentence, "As of <date>, the latest [stable] version of <subject> is <value>.", with that
  date as its effective date and its recorded date. Every system receives exactly the same sentence. The wording is a
  rendering of the record, not text taken from a PEP, and that limit is stated in the report.
* Questions: the current value, the previous value, and "on <date>" for the middle of every validity interval
  (so the answer cannot sit on a release-day boundary). The gold value is the record whose interval contains that date.
* Unanswerable: three questions about versions or products that no record mentions (verified absent).

    python -m benchmarks.real_temporal [--out benchmarks/reports]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .datasets import Event, Question, Scenario
from .run import aggregate, hardware, run_scenario
from .systems import available_systems

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "python_releases.json"
SCENARIO = "real_python_releases"
ABSENT = [
    ("What is the latest version of Python 3.15?", "3.15"),
    ("What was the latest version of Python 3.11 on 2023-01-01?", "3.11"),
    ("What is the latest version of PyPy?", "PyPy"),
]


def _series(records: list[dict], predicate: str) -> list[dict]:
    return sorted((r for r in records if r["predicate"] == predicate), key=lambda r: r["valid_from"])


def build() -> tuple[Scenario, dict]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    records = data["records"]
    ordered = sorted(enumerate(records), key=lambda p: (p[1]["valid_from"], p[0]))
    events: list[Event] = []
    for idx, (_, r) in enumerate(ordered):
        kind = "latest stable version" if r["predicate"] == "latest stable version" else "latest version"
        text = f"As of {r['valid_from']}, the {kind} of {r['subject']} is {r['object']}."
        stamp = f"{r['valid_from']}T12:00:00+00:00"
        events.append(Event(idx, "add", text, "u1", stamp, effective_at=stamp, source_type="document"))
    flat = " ".join(e.text for e in events).lower()
    questions: list[Question] = []

    def add(text: str, gold: str, wrong: list[str], tag: str) -> None:
        rel = [e.idx for e in events if gold in e.text and re.search(rf"\b{re.escape(gold)}\b", e.text)]
        questions.append(Question(f"rt{len(questions)}", SCENARIO, text, "u1", [gold], wrong, rel, tag=tag))

    for predicate, label in (("latest version", "latest version of Python 3.14"), ("latest stable version", "latest stable version of Python")):
        series = _series(records, predicate)
        values = [r["object"] for r in series]
        add(f"What is the {label}?", values[-1], [v for v in values if v != values[-1]], "current")
        if len(values) > 1:
            add(f"What was the previous {label}?", values[-2], [v for v in values if v != values[-2]], "previous")
        for i, r in enumerate(series):
            start = date.fromisoformat(r["valid_from"])
            end = date.fromisoformat(series[i + 1]["valid_from"]) if i + 1 < len(series) else start + timedelta(days=14)
            mid = start + (end - start) / 2
            add(f"What was the {label} on {mid.isoformat()}?", r["object"], [v for v in values if v != r["object"]], "as_of")
    for q_text, term in ABSENT:
        if re.search(rf"\b{re.escape(term.lower())}\b", flat):
            raise SystemExit(f"integrity: {term!r} occurs in the records, so {q_text!r} is not unanswerable")
        questions.append(Question(f"ru{len(questions)}", SCENARIO, q_text, "u1", answerable=False, tag="absent"))
    sc = Scenario(SCENARIO, "Dated CPython releases (PEP 693/719/745): current, previous and as-of questions.", events, questions, "temporal reasoning on real data")
    return sc, data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MemoraOS real temporal benchmark")
    ap.add_argument("--out", default="benchmarks/reports")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    sc, data = build()
    raw: dict = defaultdict(lambda: defaultdict(list))
    extras: dict = defaultdict(lambda: defaultdict(list))
    for system in available_systems(True):
        collected: dict = {}
        try:
            run_scenario(sc, system, collected)
        finally:
            system.close()
        for name, per in collected.items():
            raw[name][SCENARIO].extend(per[SCENARIO]["results"])
            extras[name][SCENARIO].append(per[SCENARIO]["extra"])
    metrics = aggregate(raw, extras)
    by_tag: dict[str, dict[str, list[float]]] = {}
    for name, per in raw.items():
        groups: dict[str, list[float]] = defaultdict(list)
        for r in per[SCENARIO]:
            groups[r["tag"]].append(float(r["correct"]))
        by_tag[name] = {k: round(sum(v) / len(v), 4) for k, v in sorted(groups.items())}
    counts: dict[str, int] = defaultdict(int)
    for q in sc.questions:
        counts[q.tag] += 1
    report = {
        "benchmark": "MemoraOS real temporal benchmark",
        "command": "python -m benchmarks.real_temporal",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": hardware(),
        "data": {"file": "data/python_releases.json", "records": len(data["records"]), "sources": data["sources"], "retrieved_on": data["retrieved_on"]},
        "questions": dict(counts),
        "metrics": {k: v["scenarios"][SCENARIO] | {"pooled_accuracy_ci95": v["pooled_accuracy_ci95"]} for k, v in metrics.items()},
        "by_tag": by_tag,
        "wall_clock_seconds": round(time.perf_counter() - t0, 1),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "real_temporal_results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "REAL_TEMPORAL.md").write_text(render(report), encoding="utf-8")
    print(f"wrote {out / 'real_temporal_results.json'} and REAL_TEMPORAL.md")
    return 0


ORDER = ["bm25", "vector", "hybrid_rag", "hybrid_rag_top1", "hybrid_rag_gated", "memoraos_hybrid_only", "memoraos"]


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def render(rep: dict) -> str:
    m, d = rep["metrics"], rep["data"]
    names = sorted(m, key=lambda n: ORDER.index(n) if n in ORDER else 99)
    tags = ["current", "previous", "as_of", "absent"]
    total = sum(rep["questions"].values())
    counts = ", ".join(str(rep["questions"].get(t, 0)) + " " + t for t in tags)
    L = ["# Real temporal benchmark\n", "_Generated by `python -m benchmarks.real_temporal`; every number comes from `real_temporal_results.json`._\n"]
    L.append(f"- Data: {d['records']} real dated release records copied from {', '.join(d['sources'].values())} (retrieved {d['retrieved_on']}), file `{d['file']}`.")
    L.append(f"- Questions: {total} ({counts}). Gold answers are computed from the real dates; \"as_of\" dates are the middle of each validity interval.")
    L.append("- Every system receives the same sentence per record. The sentence is a rendering of the record (`As of <date>, the latest version of <subject> is <value>.`), not text taken from a PEP. Scoring is mechanical (gold present, no other version present; unanswerable questions must be refused). No LLM anywhere.\n")
    L.append("| System | All [95% CI] | " + " | ".join(tags) + " |")
    L.append("|---|---|" + "|".join("---" for _ in tags) + "|")
    for n in names:
        x, k = m[n], rep["by_tag"][n]
        lo, hi = x["accuracy_ci95"]
        L.append(f"| {'**'+n+'**' if n == 'memoraos' else n} | {_pct(x['accuracy'])} [{_pct(lo)}, {_pct(hi)}] | " + " | ".join(_pct(k.get(t)) for t in tags) + " |")
    L.append("\n## Limits\n")
    L.append("- 3 sources, one fact family (Python releases), small question count: this checks the mechanism on real dates, it is not a general benchmark.\n- The sentences are templated renderings of real records. The unanswerable questions were written by the project.\n- Mem0, Graphiti, Hindsight and Memorilla were not run.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
