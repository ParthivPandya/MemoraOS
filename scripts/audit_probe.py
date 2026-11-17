"""v0.1 baseline probe: what does the engine ACTUALLY do for the v0.2 spec's own examples?

Run: python scripts/audit_probe.py   (prints a verdict per probe; used to write docs/V02_REPOSITORY_AUDIT.md)
"""

from __future__ import annotations

import sys

from memoraos import MemoryOS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
U = "u"
rows: list[tuple[str, str, str]] = []


def probe(name: str, setup: list[str], question: str, expect: str, *, should_answer: bool = True, **kw) -> None:
    m = MemoryOS.in_memory()
    for s in setup:
        m.remember(s, user_id=U, **kw)
    r = m.recall(question, user_id=U)
    ok = (expect.lower() in r.answer.lower()) if should_answer else (r.status == "insufficient_evidence")
    rows.append((("PASS" if ok else "FAIL"), name, f"{r.status} | {r.strategy} | {r.answer[:90]!r}"))
    m.close()


# --- 6.3 paraphrase normalization: all four should give the same current salary -----------------
for phrase in ("My salary is 32 LPA.", "I earn 32 lakhs annually.", "My annual compensation is 32 lakh rupees.", "My CTC is ₹32 lakh per annum."):
    probe(f"paraphrase: {phrase}", [phrase], "What is my salary?", "32")

# equivalence across paraphrases must not depend on "later self-report supersedes": use document sources
m = MemoryOS.in_memory()
m.remember("My salary is 32 LPA.", user_id=U, source_type="document")
r = m.remember("I earn 32 lakhs annually.", user_id=U, source_type="document")
res = m.recall("What is my salary?", user_id=U)
rows.append(("PASS" if res.status == "answered" and not r.conflicts else "FAIL", "paraphrases (document sources) are not a conflict", f"status={res.status} conflicts={len(r.conflicts)}"))
m.close()

m = MemoryOS.in_memory()
m.remember("My salary is 32 LPA.", user_id=U, source_type="document")
r = m.remember("My annual compensation is 32 lakh rupees.", user_id=U, source_type="document")
rows.append(("PASS" if not r.conflicts else "FAIL", "32 LPA == 32 lakh rupees (units, document sources)", f"conflicts={[c.values for c in r.conflicts]}"))
m.close()

# all four paraphrases should normalise to ONE canonical (subject, predicate, value) triple
keys = set()
for phrase in ("My salary is 32 LPA.", "I earn 32 lakhs annually.", "My annual compensation is 32 lakh rupees.", "My CTC is ₹32 lakh per annum."):
    mm = MemoryOS.in_memory()
    mm.remember(phrase, user_id=U)
    f = mm.facts(user_id=U)
    keys.add(tuple((x.subject_key, x.predicate, x.object_key) for x in f))
    mm.close()
rows.append(("PASS" if len(keys) == 1 else "FAIL", "four salary paraphrases -> one canonical fact", f"{len(keys)} distinct canonical forms: {sorted(keys)}"))

# --- 8: evidence fusion example from the spec ---------------------------------------------------
probe("fusion: region of project Alice manages", ["Alice manages Project Atlas.", "Project Atlas uses Azure Functions.", "Azure Functions is deployed in West Europe."],
      "Which Azure region is used by the project Alice manages?", "West Europe")

# --- 6.4 safety cases -----------------------------------------------------------------------------
probe("negation: 'I do not use Angular'", ["I do not use Angular."], "What do I use?", "angular", should_answer=False)
probe("pronoun subject must not establish an answer about a named entity", ["It is hosted in Pune."], "Where is the billing service hosted?", "pune", should_answer=False)
probe("unsupported inference (no 'married' stated)", ["Alice lives in Pune.", "Bob lives in Pune."], "Who is Alice married to?", "", should_answer=False)
probe("correction wording", ["My salary is 28 LPA.", "Correction: my salary is actually 30 LPA."], "What is my salary?", "30")
probe("numeric change in place", ["The budget is 5 lakh.", "The budget is 7 lakh."], "What is the budget?", "7")
probe("multiple entities in one sentence (as facts, not just a passage)", ["Alice works at Contoso and Bob works at Fabrikam."], "Where does Bob work?", "Fabrikam")
m_ = MemoryOS.in_memory()
m_.remember("Alice works at Contoso and Bob works at Fabrikam.", user_id=U)
rows.append(("PASS" if len(m_.facts(user_id=U)) == 2 else "FAIL", "conjunction yields two facts", f"facts={[(f.subject, f.predicate, f.object) for f in m_.facts(user_id=U)]}"))
m_.close()

# --- 7: query-side robustness ----------------------------------------------------------------------
probe("question synonym: 'How much does Priya make?'", ["Priya earns 40 LPA."], "How much does Priya make?", "40")
probe("indirect phrasing", ["You can reach Priya in Pune these days."], "Where does Priya live?", "pune")
probe("inverted phrasing", ["Pune is where Priya lives."], "Where does Priya live?", "pune")

# --- structural checks ---------------------------------------------------------------------------------
m = MemoryOS.in_memory()
cols = {r["name"] for r in m.db.query("PRAGMA table_info(embeddings)")}
rows.append(("PASS" if {"provider", "model_version", "dim", "status"} <= cols else "FAIL", "embedding metadata persisted (provider/version/status)", f"embeddings columns={sorted(cols)}"))
fcols = {r["name"] for r in m.db.query("PRAGMA table_info(facts)")}
rows.append(("PASS" if {"extraction_method", "source_span_start"} <= fcols else "FAIL", "facts record extraction method + source span", f"facts has method={'extraction_method' in fcols} span={'source_span_start' in fcols}"))
tables = {r["name"] for r in m.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
rows.append(("PASS" if "extraction_attempts" in tables else "FAIL", "failed extraction attempts recorded", f"extraction_attempts table present={'extraction_attempts' in tables}"))
from memoraos.config import Settings  # noqa: E402

fields = set(Settings.model_fields)
rows.append(("PASS" if {"fusion_strategy", "fusion_weights"} <= fields else "FAIL", "fusion strategy and weights configurable", f"settings has fusion_strategy={'fusion_strategy' in fields} fusion_weights={'fusion_weights' in fields}"))
rows.append(("PASS" if "rerank" in "".join(fields) else "FAIL", "reranker wired into retrieval", "RerankProvider exists but recall pipeline never calls it (verified by grep in audit)"))
m.close()

width = max(len(n) for _, n, _ in rows)
for verdict, name, detail in rows:
    print(f"{verdict}  {name:<{width}}  {detail}")
print(f"\n{sum(v == 'PASS' for v, _, _ in rows)}/{len(rows)} probes pass on this build")
