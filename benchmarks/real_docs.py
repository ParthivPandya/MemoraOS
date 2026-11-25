"""Real-document benchmark: question answering over MemoraOS's OWN documentation.

No generated data. The corpus is the project's real Markdown documents (docs/**, CHANGELOG.md, SECURITY.md,
ROADMAP) split into heading sections exactly as written. The questions are hand-written about what those documents
say. Integrity is enforced, not assumed:

* every gold answer must occur verbatim in at least one section (otherwise the run aborts);
* every unanswerable question names a term that must NOT occur anywhere in the corpus (otherwise it aborts).

    python -m benchmarks.real_docs [--out benchmarks/reports]

The same systems and the same mechanical judge as ``benchmarks.run`` are used. Limits (stated in the report):
the questions are authored by the project, the corpus is small, and README.md / docs/EVIDENCE.md are excluded so a
question can never be answered from the page that reports the result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .datasets import Event, Question, Scenario
from .run import aggregate, hardware, run_scenario
from .systems import TOP_K, MemoraSystem, available_systems

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = {"docs/EVIDENCE.md"}
# Documents about the benchmarks, the competitors and the next release are excluded so the corpus stays the v0.2
# documentation it was written against (a document that discusses the questions would contaminate the answers).
EXCLUDE_PATTERNS = (
    r"docs/NEXT_[A-Z_]+\.md", r"docs/COMPETITIVE_INTELLIGENCE\.md", r"docs/MEMORY_CI\.md", r"docs/ADR/00(?:0[89]|[1-9]\d)-.*\.md",
    r"docs/DOCKER\.md", r"docs/PUBLIC_BENCHMARKS\.md", r"docs/SCALING\.md", r"docs/CITATIONS\.md", r"docs/AGENT_WORKFLOW\.md",
        r"docs/MCP\.md", r"docs/VAULT_SYNC\.md", r"docs/INTEGRATIONS\.md", r"docs/CAUSAL_AND_REPLAY\.md",
)
FILES = ["CHANGELOG.md", "SECURITY.md"]
SCENARIO = "real_docs_qa"


def _excluded(rel: str) -> bool:
    return rel in EXCLUDE or any(re.fullmatch(p, rel) for p in EXCLUDE_PATTERNS)

# (question, gold substring that must appear in the source, kind tag)
ANSWERABLE: list[tuple[str, str, str]] = [
    ("Which hash function chains the audit events?", "SHA256", "security"),
    ("How are API keys stored on disk?", "SHA-256 hashes", "security"),
    ("Which address does the REST API bind to by default?", "127.0.0.1", "security"),
    ("What placeholder replaces a detected secret before it is stored?", "[REDACTED:type]", "security"),
    ("What is the maximum number of characters accepted as input text?", "2 M character", "security"),
    ("How does the memory rendering protect against injected instructions in retrieved text?", "untrusted", "security"),
    ("Which setting is the score gap within which cheaper strategies win?", "cost_tolerance", "routing"),
    ("Which setting sets the minimum labelled outcomes before a learned routing override applies?", "learning_min_samples", "routing"),
    ("Which confidence interval bound must a challenger strategy meet to replace the default?", "Wilson", "routing"),
    ("Why did the Windows CI test fail intermittently?", "15 ms", "decisions"),
    ("What caused the wrong latest value to be chosen in that CI failure?", "random fact id", "decisions"),
    ("How much is a repeated system timestamp bumped?", "1 µs", "decisions"),
    ("Which exception is raised when a model name is reused with a different vector dimension?", "EmbeddingModelMismatch", "decisions"),
    ("Which function wraps embedding providers that implement only the v0.1 protocol?", "adapt_embedder", "decisions"),
    ("What weight do expanded query lists get by default?", "0.5 by default", "decisions"),
    ("What is the canonical value key for a salary of 32 LPA?", "money:INR:annual:3200000", "decisions"),
    ("For which kind of predicate are monthly amounts annualized?", "compensation", "decisions"),
    ("What happens to prompt-injection sentences before the LLM extraction call?", "removed before the call", "decisions"),
    ("Which table records every extraction attempt?", "extraction_attempts", "decisions"),
    ("How is confidence computed over the steps of a fused evidence path?", "minimum", "decisions"),
    ("What kind of storage changes does ADR-0001 allow?", "additive", "decisions"),
    ("What is the arXiv number of the Memorilla paper?", "2610.21375", "latent"),
    ("How much GPU memory does the Memorilla README call for?", "80 GB", "latent"),
    ("How many training stages does Memorilla need?", "three training stages", "latent"),
    ("Which class is the CPU slot-attention baseline for latent memory?", "SlotAttentionMemory", "latent"),
    ("What per-query latency budget do the regression tests enforce?", "250 ms", "performance"),
    ("What is the maximum number of memories per consolidation run?", "5000", "performance"),
    ("Which standard memory benchmarks are planned as adapters in the roadmap?", "LongMemEval", "roadmap"),
    ("What is the name of the automatic backup taken before a schema upgrade?", ".bak-v1", "changelog"),
    ("Which schema migration added fact polarity and extraction method columns?", "Schema migration 2", "changelog"),
]

# (question, term that must not occur anywhere in the corpus, kind tag)
UNANSWERABLE: list[tuple[str, str, str]] = [
    ("What is the monthly price of the hosted MemoraOS plan?", "pricing", "absent_topic"),
    ("Which Kubernetes version does MemoraOS require?", "kubernetes", "absent_topic"),
    ("Who founded the company behind MemoraOS?", "founded", "absent_topic"),
    ("Which GraphQL endpoint exposes recall?", "graphql", "absent_topic"),
    ("What is the Windows installer filename?", "installer", "absent_topic"),
    ("Which default port does the Redis cache use?", "redis", "absent_topic"),
    ("Which SQLAlchemy version does the storage layer use?", "sqlalchemy", "absent_topic"),
    ("Which Android versions are supported by the mobile app?", "android", "absent_topic"),
    ("What is the SOC 2 certification status?", "soc 2", "absent_topic"),
    ("Which cloud region hosts the MemoraOS SaaS?", "saas", "absent_topic"),
    ("How many GitHub stars does the repository have?", "stars", "absent_topic"),
    ("Which Prometheus metric tracks recall latency?", "prometheus", "absent_topic"),
]

# Held-out set: written BEFORE any retrieval/answering change was made in response to the dev-set failures, and never
# used for tuning. It exists so improvements can be checked on questions the changes were not shaped by.
HELDOUT_ANSWERABLE: list[tuple[str, str, str]] = [
    ("When several strategies score within the tolerance, which one does the router choose?", "cheapest", "routing"),
    ("Which retrieval strategy does a question like 'Find error E4021' use?", "bm25", "routing"),
    ("How many logical CPUs did the performance measurements run on?", "8 logical CPUs", "performance"),
    ("Which Python version were the performance numbers measured with?", "3.14.3", "performance"),
    ("How much RAM did the benchmark machine have?", "7.7 GB", "performance"),
    ("Which security control prevents SQL injection?", "parameterised", "security"),
    ("What does forget() do to the stored memory rows?", "hard-delete", "security"),
    ("Is encryption at rest implemented in code?", "AES-256-GCM", "security"),
    ("Which tool is suggested for disk encryption of the data directory on Windows?", "BitLocker", "security"),
    ("Which Python version does the Memorilla reproduction plan require?", "Python 3.11", "latent"),
    ("What is the default value of adaptive_learning?", "adaptive_learning=False", "routing"),
    ("What happens when two values share the same explicit effective date?", "same date", "temporal"),
    ("Which version pair is the example of a possible version change?", "Angular 16", "temporal"),
    ("Which kind of relative date in stored text is not handled?", "last month", "temporal"),
    ("Which database table is append-only and hash-chained?", "append-only", "temporal"),
    ("What is the name of the typed model for an extracted fact in ADR-0002?", "StructuredFact", "decisions"),
]
HELDOUT_UNANSWERABLE: list[tuple[str, str, str]] = [
    ("What OAuth scopes does the API require?", "oauth", "absent_topic"),
    ("Which Terraform module deploys MemoraOS?", "terraform", "absent_topic"),
    ("Which Helm chart version is current?", "helm", "absent_topic"),
    ("Which PagerDuty service receives incident alerts?", "pagerduty", "absent_topic"),
    ("What uptime does the service level agreement guarantee?", "uptime", "absent_topic"),
    ("Which Snowflake warehouse stores the benchmark results?", "snowflake", "absent_topic"),
]

# Validation set V2: written for the answerability work (spec 8.3) BEFORE any answerability change was implemented, from
# documents the dev and held-out questions barely touch (API, MCP, design, architecture, performance, roadmap). It is
# evaluated by `benchmarks.answerability` only; `real_docs.build()` excludes it unless asked, so the published
# real-docs numbers stay comparable. A term written "a+b+c" in an unanswerable question means: these words must never
# all occur in one section (every word is known to the corpus, but the fact is not there).
VALIDATION_ANSWERABLE: list[tuple[str, str, str]] = [
    ("Which method returns the value timeline for a subject and predicate?", "history(subject=", "api"),
    ("Which role is needed to delete everything a user owns through the REST API?", "forget everything the user owns", "api"),
    ("What status code does the API return for a bad or missing key?", "401", "api"),
    ("Which error is raised when a memory is visible but not yours to modify?", "PermissionDenied", "api"),
    ("Which TypeScript package provides the client?", "@memoraos/sdk", "api"),
    ("Which MCP tool lets a model correct a memory?", "memora_correct", "mcp"),
    ("What does the MCP server do with a user_id the model supplies?", "ignored", "mcp"),
    ("What source reliability does a user statement get?", "user statement 0.9", "design"),
    ("What is the default chunk size?", "default 800 chars", "design"),
    ("What fraction of question terms must a passage answer cover at least?", "at least 50% of the question's content terms", "design"),
    ("What happens to old facts when a memory is corrected?", "retracted", "design"),
    ("Which reliability do consolidation summaries carry?", "reliability 0.3", "design"),
    ("Which table stores reversible entity-resolution aliases?", "reversible entity-resolution aliases", "architecture"),
    ("What does the embeddings table use as its cache key?", "(content_hash, model)", "architecture"),
    ("Which FTS5 tokenizer powers the BM25 index?", "Porter", "architecture"),
    ("What vector index does the architecture use today?", "Brute-force cosine", "architecture"),
    ("How is time represented so that ordering is lexicographic?", "Fixed-width UTC ISO strings", "architecture"),
    ("Which graph library is built on demand from facts?", "NetworkX", "architecture"),
    ("What is the default embedder?", "Feature-hashing", "architecture"),
    ("Which table keeps tokens, cost and latency for provider calls?", "provider_usage", "architecture"),
    ("How long does the committed report say a median query takes for MemoraOS?", "2.6 ms", "performance"),
    ("How many milliseconds per event does MemoraOS spend on ingest in the committed report?", "5.4 ms", "performance"),
    ("Which component caches the vector matrix per scope?", "VectorIndex._matrix", "performance"),
    ("What invalidates the vector matrix cache?", "event sequence number", "performance"),
    ("Which roadmap item concerns the reranking step?", "Reranker integration", "roadmap"),
]
VALIDATION_UNANSWERABLE: list[tuple[str, str, str]] = [
    ("Which Elasticsearch cluster stores the vector index?", "elasticsearch", "absent_term"),
    ("Which Datadog dashboard shows recall latency?", "datadog", "absent_term"),
    ("Which Jenkins job publishes the package?", "jenkins", "absent_term"),
    ("What is the Okta tenant for single sign-on?", "okta", "absent_term"),
    ("Which Cassandra keyspace holds the events?", "cassandra", "absent_term"),
    ("What is the Twilio number for alerts?", "twilio", "absent_term"),
    ("What is the maximum number of API keys a tenant can hold?", "maximum+keys+tenant", "x"),
    ("How often are API keys rotated?", "rotate+keys", "x"),
    ("When do API keys expire?", "expire+keys", "x"),
    ("Which user receives a notification when consolidation fails?", "notification+consolidation", "x"),
    ("Which cipher encrypts the embedding cache?", "cipher+embedding", "x"),
    ("What is the rate limit per API key?", "rate+limit+keys", "x"),
    ("Which language is the dashboard backend written in?", "dashboard+language", "x"),
    ("How many memories can a single user store?", "memories+single+user", "x"),
    ("In which format is the audit log exported?", "audit+export+format", "x"),
]


def corpus_files() -> list[Path]:
    paths = sorted(p for p in (ROOT / "docs").rglob("*.md") if not _excluded(p.relative_to(ROOT).as_posix()))
    return [*paths, *(ROOT / f for f in FILES)]


def sections(path: Path) -> list[tuple[str, str]]:
    """(heading path, text) for every heading section, text exactly as written."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^(?=#{1,3} )", text)
    out = []
    for part in parts:
        part = part.strip()
        if len(part) >= 40:
            out.append((part.splitlines()[0].lstrip("# ").strip(), part))
    return out


def build(root: Path = ROOT, validation: bool = False) -> tuple[Scenario, dict[int, str], str]:
    events: list[Event] = []
    origin: dict[int, str] = {}
    digest = hashlib.sha256()
    for path in corpus_files():
        rel = path.relative_to(root).as_posix()
        for heading, text in sections(path):
            idx = len(events)
            events.append(Event(idx, "add", text, "u1", f"2026-11-17T00:{idx // 60:02d}:{idx % 60:02d}+00:00", source_type="document"))
            origin[idx] = f"{rel} > {heading}"
            digest.update(text.encode("utf-8"))
    questions: list[Question] = []
    low = [e.text.lower() for e in events]
    extra_a = [(q, g, t, "validation") for q, g, t in VALIDATION_ANSWERABLE] if validation else []
    extra_u = [(q, g, t, "validation") for q, g, t in VALIDATION_UNANSWERABLE] if validation else []
    # contamination guard: no question may appear verbatim in the corpus (a doc that quotes the test would answer it)
    flat = [re.sub(r"\s+", " ", t) for t in low]
    for q_text in [q for q, *_ in ANSWERABLE + HELDOUT_ANSWERABLE + UNANSWERABLE + HELDOUT_UNANSWERABLE] + [q for q, *_ in extra_a + extra_u]:
        needle = re.sub(r"\s+", " ", q_text.lower().rstrip("?").strip())
        if any(needle in t for t in flat):
            raise SystemExit(f"integrity: the question {q_text!r} is quoted in the corpus; reword the document, not the question")
    answerable = [(q, g, t, "dev") for q, g, t in ANSWERABLE] + [(q, g, t, "heldout") for q, g, t in HELDOUT_ANSWERABLE] + extra_a
    unanswerable = [(q, g, t, "dev") for q, g, t in UNANSWERABLE] + [(q, g, t, "heldout") for q, g, t in HELDOUT_UNANSWERABLE] + extra_u
    for i, (q, gold, tag, split) in enumerate(answerable):
        rel = [e.idx for e in events if gold.lower() in e.text.lower()]
        if not rel:
            raise SystemExit(f"integrity: gold {gold!r} for {q!r} occurs in no section; fix the question or the corpus")
        questions.append(Question(f"rd{i}", SCENARIO, q, "u1", [gold], [], rel, tag=f"{split}/{tag}"))
    for j, (q, term, tag, split) in enumerate(unanswerable):
        parts = term.split("+")
        if tag == "x":  # label by what is true of the corpus: are all of this question's key words known to it?
            tag = "known_words" if all(any(re.search(rf"\b{re.escape(p)}", t) for t in low) for p in parts) else "absent_term"
        # "a+b": every word is known to the corpus, but they must never all occur in one section
        present = any(all(re.search(rf"\b{re.escape(p)}" + (r"\b" if len(parts) == 1 else ""), t) for p in parts) for t in low)
        if present:
            raise SystemExit(f"integrity: {term!r} occurs in the corpus, so {q!r} is not unanswerable")
        questions.append(Question(f"ru{j}", SCENARIO, q, "u1", answerable=False, tag=f"{split}/{tag}"))
    sc = Scenario(SCENARIO, "Questions about MemoraOS's own documentation (real text, project-authored questions).", events, questions, "real-document QA")
    return sc, origin, digest.hexdigest()


def transcripts(sc: Scenario, origin: dict[int, str]) -> list[dict]:
    """What MemoraOS actually answered, with the sections it cited."""
    system = MemoraSystem()
    try:
        system.ingest(sc.events)
        rows = []
        for q in sc.questions:
            r = system.eng.recall(q.text, user_id=q.user, tenant_id="bench", top_k=TOP_K, use_cache=False)
            cited = [origin[system.mem_to_event[e.memory_id]] for e in r.evidence if e.memory_id in system.mem_to_event]
            correct = (not r.supported) if not q.answerable else (r.supported and all(g.lower() in r.answer.lower() for g in q.gold))
            rows.append({
                "qid": q.qid, "question": q.text, "tag": q.tag, "answerable": q.answerable, "gold": q.gold, "status": r.status,
                "strategy": r.strategy, "answer": r.answer, "cited": list(dict.fromkeys(cited))[:3], "correct": bool(correct),
            })
        return rows
    finally:
        system.close()


def knob_systems() -> list:
    """MemoraOS at looser `min_anchor_coverage` values: the precision/recall trade-off made visible, not hidden."""
    from memoraos.config import Settings

    return [
        MemoraSystem(label=f"memoraos[anchor={a}]", settings=Settings(min_anchor_coverage=a), description=f"MemoraOS with min_anchor_coverage={a}")
        for a in (0.4, 0.25, 0.0)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MemoraOS real-document benchmark")
    ap.add_argument("--out", default="benchmarks/reports")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    sc, origin, corpus_sha = build()
    raw: dict = defaultdict(lambda: defaultdict(list))
    extras: dict = defaultdict(lambda: defaultdict(list))
    for system in [*available_systems(True), *knob_systems()]:
        collected: dict = {}
        try:
            run_scenario(sc, system, collected)
        finally:
            system.close()
        for name, per in collected.items():
            raw[name][SCENARIO].extend(per[SCENARIO]["results"])
            extras[name][SCENARIO].append(per[SCENARIO]["extra"])
    metrics = aggregate(raw, extras)
    by_kind: dict[str, dict[str, float]] = {}
    for name, per in raw.items():
        groups: dict[str, list[float]] = defaultdict(list)
        for r in per[SCENARIO]:
            split, topic = r["tag"].split("/", 1)
            groups[f"split:{split}"].append(float(r["correct"]))
            groups[f"{split}:{'answerable' if r['answerable'] else 'unanswerable'}"].append(float(r["correct"]))
            groups[f"topic:{topic}"].append(float(r["correct"]))
        by_kind[name] = {k: statistics.fmean(v) for k, v in sorted(groups.items())}
    trans = transcripts(sc, origin)
    before = None
    before_path = ROOT / "benchmarks" / "reports" / "real_docs_before_fixes.json"
    if before_path.exists():
        b = json.loads(before_path.read_text(encoding="utf-8"))
        before = {"corpus_sha256": b["corpus"]["sha256"], "memoraos": b["by_kind"]["memoraos"], "hybrid_rag_gated": b["by_kind"]["hybrid_rag_gated"], "note": "same questions, run before the defect fixes listed in docs/RETRIEVAL.md"}
    report = {
        "benchmark": "MemoraOS real-document benchmark",
        "command": "python -m benchmarks.real_docs",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": hardware(),
        "corpus": {"files": len(corpus_files()), "sections": len(sc.events), "characters": sum(len(e.text) for e in sc.events), "sha256": corpus_sha},
        "questions": {"answerable": len(ANSWERABLE) + len(HELDOUT_ANSWERABLE), "unanswerable": len(UNANSWERABLE) + len(HELDOUT_UNANSWERABLE), "dev": len(ANSWERABLE) + len(UNANSWERABLE), "heldout": len(HELDOUT_ANSWERABLE) + len(HELDOUT_UNANSWERABLE)},
        "top_k": TOP_K,
        "metrics": {k: v["scenarios"][SCENARIO] | {"pooled_accuracy_ci95": v["pooled_accuracy_ci95"]} for k, v in metrics.items()},
        "by_kind": by_kind,
        "before_fixes": before,
        "transcripts": trans,
        "wall_clock_seconds": round(time.perf_counter() - t0, 1),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "real_docs_results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "REAL_DOCS.md").write_text(render(report), encoding="utf-8")
    print(f"wrote {out / 'real_docs_results.json'} and REAL_DOCS.md")
    return 0


ORDER = ["bm25", "vector", "hybrid_rag", "hybrid_rag_top1", "hybrid_rag_gated", "memoraos_hybrid_only", "memoraos", "memoraos[anchor=0.4]", "memoraos[anchor=0.25]", "memoraos[anchor=0.0]"]


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def render(rep: dict) -> str:
    m, c = rep["metrics"], rep["corpus"]
    names = sorted(m, key=lambda n: ORDER.index(n) if n in ORDER else 99)
    L = ["# Real-document benchmark\n", "_Generated by `python -m benchmarks.real_docs`; every number comes from `real_docs_results.json`._\n"]
    L.append(f"- Corpus: MemoraOS's own documentation: {c['files']} files, {c['sections']} heading sections, {c['characters']:,} characters, SHA-256 `{c['sha256'][:16]}…`. Text is used exactly as written; `README.md` and `docs/EVIDENCE.md` are excluded.")
    L.append(f"- Questions: {rep['questions']['answerable']} answerable (gold string verified to occur in the corpus) and {rep['questions']['unanswerable']} unanswerable (key term verified to be absent from the corpus). Authored by the project. **Dev set** ({rep['questions']['dev']} questions) was used to find and fix defects; the **held-out set** ({rep['questions']['heldout']} questions) was written before any fix and never used for tuning.")
    L.append(f"- Scoring: mechanical (answer contains the gold string; unanswerable questions must be refused). Top-k {rep['top_k']}. No LLM anywhere. Hardware: {rep['environment']['platform']}, Python {rep['environment']['python']}.\n")
    L.append("| System | All questions [95% CI] | Dev | **Held-out** | Held-out answerable | Held-out unanswerable refused | Evidence hit | MRR |")
    L.append("|---|---|---|---|---|---|---|---|")
    for n in names:
        k, x = rep["by_kind"][n], m[n]
        lo, hi = x["accuracy_ci95"]
        L.append(f"| {'**'+n+'**' if n == 'memoraos' else n} | {_pct(x['accuracy'])} [{_pct(lo)}, {_pct(hi)}] | {_pct(k.get('split:dev'))} | **{_pct(k.get('split:heldout'))}** | {_pct(k.get('heldout:answerable'))} | {_pct(k.get('heldout:unanswerable'))} | {_pct(x.get('evidence_coverage'))} | {_pct(x.get('mrr'))} |")
    if rep.get("before_fixes"):
        b, a = rep["before_fixes"]["memoraos"], rep["by_kind"]["memoraos"]
        L.append("\n## MemoraOS before and after the real-data fixes\n")
        L.append("The first run of this benchmark exposed defects that the synthetic suite had hidden (listed in [docs/RETRIEVAL.md](../../docs/RETRIEVAL.md)). The held-out questions were frozen before any fix. The corpus has grown since the \"before\" run (these documents describe the fixes), so read the change as indicative, not exact.\n")
        L.append("| MemoraOS | Dev | Held-out | Held-out answerable | Held-out unanswerable refused |")
        L.append("|---|---|---|---|---|")
        L.append(f"| before fixes | {_pct(b.get('split:dev'))} | {_pct(b.get('split:heldout'))} | {_pct(b.get('heldout:answerable'))} | {_pct(b.get('heldout:unanswerable'))} |")
        L.append(f"| after fixes | {_pct(a.get('split:dev'))} | {_pct(a.get('split:heldout'))} | {_pct(a.get('heldout:answerable'))} | {_pct(a.get('heldout:unanswerable'))} |")
    L.append("\n`memoraos[anchor=x]` rows are the same engine with `min_anchor_coverage=x`: the lower the value, the more real questions are answered and the fewer unanswerable ones are refused. The default (`memoraos`, 0.5) is the strict end by design; see [docs/RETRIEVAL.md](../../docs/RETRIEVAL.md).")
    L.append("\n## Accuracy by question topic\n")
    tags = sorted({t for n in names for t in rep["by_kind"][n] if t.startswith("topic:")})
    L.append("| Topic | " + " | ".join(names) + " |")
    L.append("|---|" + "|".join("---" for _ in names) + "|")
    for t in tags:
        L.append(f"| {t[6:]} | " + " | ".join(_pct(rep["by_kind"][n].get(t)) for n in names) + " |")
    L.append("\n## What MemoraOS actually answered\n")
    L.append("Every row is real output. `✓`/`✗` is the mechanical judge, not a human opinion.\n")
    L.append("| | Question | Status | Strategy | Answer (as returned) | Cited section |")
    L.append("|---|---|---|---|---|---|")
    for t in rep["transcripts"]:
        ans = t["answer"].replace("\n", " ").replace("|", "\\|")
        ans = ans if len(ans) <= 180 else ans[:177] + "..."
        L.append(f"| {'✓' if t['correct'] else '✗'} | {t['question']} | {t['status']} | {t['strategy']} | {ans} | {(t['cited'] or ['–'])[0].replace('|', '/')} |")
    L.append("\n## Limits\n")
    L.append("- The corpus is small and written by the same project that is being measured, and so are the questions. Treat this as an honest end-to-end check on real text, not as an independent benchmark.\n- The held-out set is small (22 questions): differences of a few points are not significant.\n- MemoraOS's temporal and contradiction machinery is largely idle on prose documentation: this run mainly measures retrieval, answer extraction and abstention on unstructured text.\n- Mem0, Graphiti, Hindsight and Memorilla were not run.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
