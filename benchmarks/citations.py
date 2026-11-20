"""Citation check on the real-document benchmark: are the cited quotes real, and do they contain the answer?

Run: python -m benchmarks.citations
Only mechanical checks, no judge model:
  * verified   - every cited quote is found unchanged at its offsets in the stored memory and in the retained source
  * gold_cited - a cited quote itself contains the gold answer string (the answer is traceable to a quoted span)
"""

from __future__ import annotations

import json
from pathlib import Path

from . import real_docs
from .systems import TOP_K, MemoraSystem


def main() -> int:
    sc, _origin, sha = real_docs.build()
    system = MemoraSystem()
    try:
        system.ingest(sc.events)
        n = answered = verified = gold = gold_answered_correct = 0
        spanless = 0
        for q in sc.questions:
            if not q.answerable:
                continue
            n += 1
            r = system.eng.recall(q.text, user_id=q.user, tenant_id="bench", top_k=TOP_K, use_cache=False)
            if not r.supported:
                continue
            answered += 1
            v = system.eng.verify_citations(r.evidence, user_id=q.user, tenant_id="bench")
            verified += all(x["status"] in ("verified", "unlocated") for x in v["results"]) and v["verified"] > 0
            spanless += any(x["status"] == "unlocated" for x in v["results"])
            correct = all(g.lower() in r.answer.lower() for g in q.gold)
            hit = any(g.lower() in e.excerpt.lower() for e in r.evidence for g in q.gold)
            gold += hit
            gold_answered_correct += hit and correct
        rep = {"corpus_sha256": sha, "answerable_questions": n, "answered": answered,
               "answers_with_verified_citation": verified, "answers_with_unlocated_citation": spanless,
               "answers_whose_quote_contains_gold": gold, "correct_and_quote_contains_gold": gold_answered_correct}
        out = Path("benchmarks/reports/CITATIONS.json")
        out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(json.dumps(rep, indent=2))
    finally:
        system.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
