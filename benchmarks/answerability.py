"""Answerability evaluation (spec 8.2 / 8.3): precision, recall and calibration of the "answer or abstain" decision.

Runs on the real-document corpus with three disjoint question sets: ``dev`` (used to find defects), ``heldout``
(written before the v0.2 fixes) and ``validation`` (V2, written before the answerability policies existed and not
used to design them). Policies are chosen on dev and *reported* on validation; see docs/NEXT_ANSWERABILITY.md.

    python -m benchmarks.answerability [--out benchmarks/reports] [--tag baseline]

Metrics (all mechanical, no LLM): overall accuracy, answerable recall (answerable questions answered correctly),
false-abstention rate (answerable questions refused), unsupported-answer rate (unanswerable questions that
received an answer), correct-abstention rate, and for MemoraOS the Brier score / ECE of ``evidence_coverage`` used as
the stated confidence of its answers. Intervals are Wilson 95% intervals, not bootstrap.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from memoraos.config import Settings

from . import real_docs
from .stats import brier, ece, overlaps, wilson
from .systems import TOP_K, MemoraSystem, RagBaseline

SPLITS = ("dev", "heldout", "validation")


def _policy_field() -> bool:
    return "answerability" in Settings.model_fields


def systems(variants: list[tuple[str, Settings]] | None = None, embedder=None, tag: str = "") -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = [(f"hybrid_rag{tag}", RagBaseline("hybrid", embedder=embedder, label=f"hybrid_rag{tag}")), (f"hybrid_rag_gated{tag}", RagBaseline("hybrid", gate=True, embedder=embedder, label=f"hybrid_rag_gated{tag}"))]
    if variants is not None:
        out += [(n + tag, MemoraSystem(label=n + tag, settings=s, embedder=embedder)) for n, s in variants]
    elif _policy_field():
        for p in ("strict", "balanced", "high_recall", "extractive_only"):
            out.append((f"memoraos[{p}]", MemoraSystem(label=f"memoraos[{p}]", settings=Settings(answerability=p))))
    else:
        out.append(("memoraos[default]", MemoraSystem(label="memoraos[default]")))
    return out


def run_system(sc, system) -> list[dict]:
    system.ingest(sc.events)
    rows = []
    for q in sc.questions:
        conf = None
        if isinstance(system, MemoraSystem):
            r = system.eng.recall(q.text, user_id=q.user, tenant_id="bench", top_k=TOP_K, use_cache=False)
            supported, answer, status, conf = r.supported, r.answer, r.status, r.confidence.evidence_coverage
        else:
            resp = system.ask(q)
            supported, answer, status = resp.supported, resp.answer, "answered" if resp.supported else "insufficient_evidence"
        correct = (not supported) if not q.answerable else (supported and all(g.lower() in answer.lower() for g in q.gold))
        split, topic = q.tag.split("/", 1)
        rows.append({"qid": q.qid, "split": split, "topic": topic, "answerable": q.answerable, "supported": bool(supported), "correct": bool(correct), "status": status, "confidence": conf})
    return rows


def summarize(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["answerable"]]
    una = [r for r in rows if not r["answerable"]]

    def rate(sub: list[dict], pred) -> dict:
        k = sum(1 for r in sub if pred(r))
        lo, hi = wilson(k, len(sub))
        return {"k": k, "n": len(sub), "rate": k / len(sub) if sub else None, "ci95": [lo, hi]}

    answered = [r for r in rows if r["supported"] and r["confidence"] is not None]
    probs, outs = [r["confidence"] for r in answered], [r["correct"] for r in answered]
    return {
        "accuracy": rate(rows, lambda r: r["correct"]),
        "answerable_recall": rate(ans, lambda r: r["correct"]),
        "false_abstention": rate(ans, lambda r: not r["supported"]),
        "wrong_answer_given": rate(ans, lambda r: r["supported"] and not r["correct"]),
        "correct_abstention": rate(una, lambda r: not r["supported"]),
        "unsupported_answer": rate(una, lambda r: r["supported"]),
        "calibration": {"n_answered": len(answered), "brier": brier(probs, outs), "ece": ece(probs, outs), "stated_confidence": "evidence_coverage"} if answered else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Answerability evaluation")
    ap.add_argument("--out", default="benchmarks/reports")
    ap.add_argument("--tag", default="")
    ap.add_argument("--splits", default=",".join(SPLITS), help="comma list of dev,heldout,validation; use dev while designing")
    ap.add_argument("--sweep", action="store_true", help="try section-support thresholds instead of the named policies")
    ap.add_argument("--embedder", default="", help="sentence-transformers model name; evaluates neural-embedding variants instead")
    args = ap.parse_args(argv)
    splits = [s for s in args.splits.split(",") if s]
    sc, _origin, sha = real_docs.build(validation="validation" in splits)
    report: dict = {
        "benchmark": "MemoraOS answerability evaluation", "command": "python -m benchmarks.answerability", "tag": args.tag, "splits": splits,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "corpus_sha256": sha,
        "counts": {s: {"answerable": sum(1 for q in sc.questions if q.tag.startswith(s + "/") and q.answerable), "unanswerable": sum(1 for q in sc.questions if q.tag.startswith(s + "/") and not q.answerable)} for s in splits},
        "systems": {},
    }
    variants = None
    embedder, tag = None, ""
    if args.embedder:
        from memoraos.providers.embeddings import SentenceTransformerEmbedder

        embedder, tag = SentenceTransformerEmbedder(args.embedder), f"[{args.embedder.split('/')[-1]}]"
        variants = [(f"memoraos[{p}]", Settings(answerability=p)) for p in ("strict", "balanced", "high_recall", "extractive_only")]
        if args.sweep:
            variants += [(f"memoraos[semantic={t}]", Settings(semantic_support=t)) for t in (0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4)]
    elif args.sweep:
        variants = [("section=off", Settings())] + [(f"section={t}", Settings(memory_support_coverage=t)) for t in (1.0, 0.9, 0.8, 0.75, 0.7, 0.6, 0.5)]
    for label, system in systems(variants, embedder, tag):
        try:
            rows = run_system(sc, system)
        finally:
            system.close()
        entry = {"all": summarize(rows), **{s: summarize([r for r in rows if r["split"] == s]) for s in splits}}
        if "validation" in splits:
            entry["validation_by_topic"] = {t: summarize([r for r in rows if r["split"] == "validation" and r["topic"] == t]) for t in ("absent_term", "known_words")}
        report["systems"][label] = entry
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"answerability{('_' + args.tag) if args.tag else ''}"
    (out / f"{stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{stem.upper()}.md").write_text(render(report), encoding="utf-8")
    print(f"wrote {out / (stem + '.json')}")
    return 0


def _p(x: dict) -> str:
    if x["rate"] is None:
        return "–"
    return f"{100 * x['rate']:.0f}% ({x['k']}/{x['n']}) [{100 * x['ci95'][0]:.0f}, {100 * x['ci95'][1]:.0f}]"


def render(rep: dict) -> str:
    splits = rep.get("splits", list(SPLITS))
    L = ["# Answerability evaluation\n", f"_Generated by `python -m benchmarks.answerability` {rep['tag'] and '(' + rep['tag'] + ')'}; every number comes from the JSON next to this file._\n"]
    c = rep["counts"]
    L.append(f"Corpus SHA-256 `{rep['corpus_sha256'][:16]}…`. Questions: " + "; ".join(f"{s}: {c[s]['answerable']} answerable + {c[s]['unanswerable']} unanswerable" for s in splits) + ". Intervals are **Wilson 95%**. Mechanical scoring, no LLM.\n")
    L.append("`validation` (V2) was written before any answerability policy existed and is the independent check; `dev` is where defects were found.\n")
    for split in [s for s in ("validation", "heldout", "dev") if s in splits]:
        L.append(f"\n## {split}\n")
        L.append("| System | Accuracy | Answerable recall | False abstention | Unsupported-answer rate | Correct abstention |\n|---|---|---|---|---|---|")
        for name, s in rep["systems"].items():
            x = s[split]
            L.append(f"| {name} | {_p(x['accuracy'])} | {_p(x['answerable_recall'])} | {_p(x['false_abstention'])} | {_p(x['unsupported_answer'])} | {_p(x['correct_abstention'])} |")
    if "validation" in splits:
        L.append("\n## Validation, unanswerable questions by kind\n")
        L.append("`absent_term`: a key word never occurs in the corpus. `known_words`: every key word occurs somewhere, but the fact does not exist (the harder case).\n")
        L.append("| System | absent_term refused | known_words refused |\n|---|---|---|")
        for name, s in rep["systems"].items():
            b = s["validation_by_topic"]
            L.append(f"| {name} | {_p(b['absent_term']['correct_abstention'])} | {_p(b['known_words']['correct_abstention'])} |")
    L.append("\n## Calibration of MemoraOS answers (all selected splits)\n")
    L.append("Stated confidence = `evidence_coverage`. Brier: lower is better. ECE with 5 bins; n is small, treat as indicative.\n")
    L.append("| System | Answered | Brier | ECE |\n|---|---|---|---|")
    for name, s in rep["systems"].items():
        cal = s["all"]["calibration"]
        if cal:
            L.append(f"| {name} | {cal['n_answered']} | {cal['brier']:.3f} | {cal['ece']:.3f} |")
    ss = list(rep["systems"].items())
    base = next((s for n, s in ss if n.startswith("hybrid_rag_gated")), None)
    ref = "validation" if "validation" in splits else splits[0]
    if base:
        L.append("\n## Reading the intervals\n")
        for name, s in ss:
            if name.startswith("memoraos"):
                a, b = s[ref]["answerable_recall"]["ci95"], base[ref]["answerable_recall"]["ci95"]
                L.append(f"- {name} vs hybrid_rag_gated, {ref} answerable recall: intervals {'overlap (no claim of a difference)' if overlaps(a, b) else 'do not overlap'}.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
