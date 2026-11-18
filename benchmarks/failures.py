"""Failure taxonomy for the real-document benchmark (spec section 8.1).

For every question MemoraOS gets wrong, assign exactly one cause from the traces the engine itself records
(`retrieval_log.explanation`: strategies tried, per-strategy notes, near-miss memories). Nothing here knows any
question or answer: the rules only compare *where the gold string lives* with *what retrieval returned* and
*what the answer policy said*.

    python -m benchmarks.failures [--out benchmarks/reports] [--anchor 0.5]

Causes used (a subset of the spec's list, the rest cannot be told apart on prose documents):
    RETRIEVAL_MISS            no section containing the gold string was among the retrieved candidates
    OVERSTRICT_ABSTENTION     the gold-bearing section WAS retrieved but the answer policy refused
    ANSWER_GENERATION_FAILURE answered, the gold-bearing section was retrieved, but the returned sentences lack the gold
    EVIDENCE_FUSION_FAILURE   answered through fusion/graph with evidence that lacks the gold
    FALSE_ACCEPTANCE          an unanswerable question received an answer
For OVERSTRICT_ABSTENTION the report also lists the guard that refused (read from the engine's notes).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from memoraos.config import Settings

from . import real_docs
from .systems import TOP_K, MemoraSystem

RETRIEVAL_DEPTH = 10  # candidates examined when asking "was the gold section retrieved at all?"


def _near_misses(system: MemoraSystem, recall_id: str) -> tuple[list[str], list[dict]]:
    row = system.eng.db.query("SELECT explanation FROM retrieval_log WHERE id=?", [recall_id])[0]
    exp = json.loads(row["explanation"])
    ids: list[str] = []
    for note in exp.get("notes", []):
        ids += re.findall(r"mem_\w+", note) if "near-miss" in note else []
    return ids, exp.get("attempts", [])


def _guard(attempts: list[dict]) -> str:
    """The reason the last attempted strategy refused, in the engine's own words, normalised to a short label."""
    notes = " ".join(n for a in attempts for n in a.get("notes", []))
    for key, label in (
        ("covers", "term coverage below the support threshold"),
        ("attribute the question asks about", "attribute-word guard"),
        ("matches only the entity", "entity-only match"),
        ("does not mention", "named entity missing from evidence"),
        ("asks for a", "answer-type guard"),
        ("never mentions", "named version missing from evidence"),
        ("NOT the case", "negation-only memory"),
        ("no candidates", "no candidates"),
    ):
        if key in notes:
            return label
    return "other / not recorded"


def classify(anchor: float | None = None, settings: Settings | None = None) -> dict:
    sc, origin, sha = real_docs.build()
    settings = settings or (Settings(min_anchor_coverage=anchor) if anchor is not None else None)
    system = MemoraSystem(settings=settings)
    rows: list[dict] = []
    try:
        system.ingest(sc.events)
        for q in sc.questions:
            r = system.eng.recall(q.text, user_id=q.user, tenant_id="bench", top_k=TOP_K, use_cache=False)
            answer = r.answer.lower() if r.supported else ""
            correct = (not r.supported) if not q.answerable else (r.supported and all(g.lower() in answer for g in q.gold))
            row = {"qid": q.qid, "question": q.text, "tag": q.tag, "answerable": q.answerable, "status": r.status, "strategy": r.strategy, "correct": bool(correct)}
            if correct:
                rows.append(row | {"cause": None})
                continue
            if not q.answerable:
                rows.append(row | {"cause": "FALSE_ACCEPTANCE", "detail": real_docs_cited(system, r, origin)})
                continue
            wide = system.eng.recall(q.text, user_id=q.user, tenant_id="bench", top_k=RETRIEVAL_DEPTH, strategy="hybrid", use_cache=False)
            near, _ = _near_misses(system, wide.recall_id)
            retrieved = {system.mem_to_event[m] for m in [e.memory_id for e in wide.evidence] + near if m in system.mem_to_event}
            gold_events = set(q.relevant)
            got = bool(retrieved & gold_events)
            _, attempts = _near_misses(system, r.recall_id)
            if not r.supported:
                row |= {"cause": "OVERSTRICT_ABSTENTION" if got else "RETRIEVAL_MISS", "guard": _guard(attempts) if got else None}
            elif r.strategy in ("fusion", "graph"):
                row |= {"cause": "EVIDENCE_FUSION_FAILURE"}
            else:
                row |= {"cause": "ANSWER_GENERATION_FAILURE" if got else "RETRIEVAL_MISS"}
            rows.append(row)
    finally:
        system.close()
    return {"corpus_sha256": sha, "anchor": anchor, "rows": rows}


def real_docs_cited(system: MemoraSystem, r, origin: dict[int, str]) -> str:
    cited = [origin[system.mem_to_event[e.memory_id]] for e in r.evidence if e.memory_id in system.mem_to_event]
    return cited[0] if cited else ""


def summarize(rep: dict) -> dict:
    rows = rep["rows"]
    wrong = [r for r in rows if not r["correct"]]
    by_cause = Counter(r["cause"] for r in wrong)
    guards = Counter(r.get("guard") for r in wrong if r.get("cause") == "OVERSTRICT_ABSTENTION")
    by_split: dict[str, Counter] = defaultdict(Counter)
    for r in wrong:
        by_split[r["tag"].split("/")[0]][r["cause"]] += 1
    answerable = [r for r in rows if r["answerable"]]
    return {
        "questions": len(rows), "wrong": len(wrong), "answerable": len(answerable), "answerable_missed": sum(1 for r in answerable if not r["correct"]),
        "by_cause": dict(by_cause), "overstrict_guards": dict(guards), "by_split": {k: dict(v) for k, v in by_split.items()},
    }


def render(rep: dict, summary: dict) -> str:
    L = ["# Failure classification (real-document benchmark)\n", "_Generated by `python -m benchmarks.failures`. Causes are read from the engine's own traces; no rule knows any question or answer._\n"]
    L.append(f"Corpus SHA-256 `{rep['corpus_sha256'][:16]}…`, `min_anchor_coverage={rep['anchor'] if rep['anchor'] is not None else 'default'}`. {summary['wrong']} of {summary['questions']} questions wrong; {summary['answerable_missed']} of {summary['answerable']} answerable questions missed.\n")
    L.append("| Cause | Count |\n|---|---|")
    for k, v in sorted(summary["by_cause"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v} |")
    if summary["overstrict_guards"]:
        L.append("\n## Which guard refused the answerable questions it should have answered\n")
        L.append("| Guard | Count |\n|---|---|")
        for k, v in sorted(summary["overstrict_guards"].items(), key=lambda kv: -kv[1]):
            L.append(f"| {k} | {v} |")
    L.append("\n## Every wrong question\n")
    L.append("| Split / topic | Question | Status | Cause | Guard or cited section |\n|---|---|---|---|---|")
    for r in rep["rows"]:
        if not r["correct"]:
            L.append(f"| {r['tag']} | {r['question']} | {r['status']} | {r['cause']} | {r.get('guard') or r.get('detail') or ''} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Classify real-document benchmark failures")
    ap.add_argument("--out", default="benchmarks/reports")
    ap.add_argument("--anchor", type=float, default=None)
    args = ap.parse_args(argv)
    rep = classify(args.anchor)
    summary = summarize(rep)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "real_docs_failures.json").write_text(json.dumps({**rep, "summary": summary}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "REAL_DOCS_FAILURES.md").write_text(render(rep, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
