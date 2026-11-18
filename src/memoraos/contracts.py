"""Memory CI (spec section 16): memory contracts you can run in CI, and a regression diff between two runs.

A contract is a JSON (or YAML, if PyYAML is installed) document::

    {
      "suite": "customer-support-memory",
      "settings": {"answerability": "balanced"},                  # optional Settings overrides
      "sources": [
        {"text": "The customer is on the Professional plan.", "user_id": "c1", "effective_at": "2024-03-01"},
        {"text": "The customer upgraded to the Enterprise plan.", "user_id": "c1", "effective_at": "2025-06-01"},
        {"file": "fixtures/notes.md", "user_id": "c1"},
        {"json": {"subject": "Acme", "predicate": "plan", "object": "Enterprise", "valid_from": "2025-06-01"}, "user_id": "c1"}
      ],
      "assertions": [
        {"id": "plan-now", "question": "What is the customer's current plan?", "user_id": "c1",
         "expected_answer": "Enterprise", "require_evidence": true},
        {"id": "plan-before", "question": "What plan did the customer have in 2024?", "user_id": "c1", "as_of": "2024-12-31",
         "expected_answer": "Professional", "require_temporal_evidence": true},
        {"id": "no-secret", "question": "What is the customer's bank password?", "user_id": "c1", "status": "insufficient_evidence"},
        {"id": "isolation", "question": "What is the customer's current plan?", "user_id": "c2", "status": "insufficient_evidence"}
      ]
    }

Assertion fields: ``question`` (required); ``status`` (answered | insufficient_evidence | conflict; defaults to
``answered`` when ``expected_answer`` is set); ``expected_answer`` (case-insensitive substring); ``forbidden_answer``;
``require_evidence``; ``require_temporal_evidence``; ``as_of``; ``user_id``/``tenant_id``; ``max_context_tokens``.

Do not put real credentials in a contract: refusal tests are written as questions whose answer must be absent.
A run is deterministic for a fixed contract and configuration. ``compare`` shows what a change did to memory
behaviour: which expectations broke, which got fixed, which statuses changed, whether abstention got worse and how
token and latency costs moved.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .engine import MemoryOS

STATUSES = {"answered", "insufficient_evidence", "conflict"}
KNOWN_ASSERTION_KEYS = {"id", "question", "status", "expected_answer", "forbidden_answer", "require_evidence", "require_temporal_evidence", "as_of", "user_id", "tenant_id", "max_context_tokens", "note"}


class ContractError(ValueError):
    """The contract file is malformed (reported before anything runs)."""


@dataclass
class AssertionResult:
    id: str
    question: str
    passed: bool
    failures: list[str]
    status: str
    answer: str
    expected_status: str
    strategy: str
    context_tokens: int
    latency_ms: float
    answerable: bool

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class SuiteResult:
    suite: str
    results: list[AssertionResult]
    config: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def to_dict(self) -> dict:
        n = len(self.results)
        return {
            "suite": self.suite, "config": self.config, "passed": self.passed, "assertions": n,
            "failed": sum(1 for r in self.results if not r.passed),
            "mean_context_tokens": statistics.fmean(r.context_tokens for r in self.results) if n else 0.0,
            "mean_latency_ms": statistics.fmean(r.latency_ms for r in self.results) if n else 0.0,
            "results": [r.to_dict() for r in self.results],
        }


def load_contract(path: str | Path) -> dict:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read contract {p}: {exc}") from exc
    try:
        if p.suffix.lower() in (".yml", ".yaml"):
            try:
                import yaml
            except ImportError as exc:
                raise ContractError("YAML contracts need PyYAML (pip install pyyaml); JSON contracts need nothing") from exc
            doc = yaml.safe_load(raw)
        else:
            doc = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"{p}: not valid {'YAML' if p.suffix.lower() in ('.yml', '.yaml') else 'JSON'}: {exc}") from exc
    return validate_contract(doc, base=p.parent)


def validate_contract(doc: Any, base: Path | None = None) -> dict:
    if not isinstance(doc, dict):
        raise ContractError("a contract must be an object with 'suite', 'sources' and 'assertions'")
    if not doc.get("suite") or not isinstance(doc["suite"], str):
        raise ContractError("'suite' (a name) is required")
    if not isinstance(doc.get("sources", []), list) or not isinstance(doc.get("assertions"), list) or not doc["assertions"]:
        raise ContractError("'sources' must be a list and 'assertions' a non-empty list")
    for i, s in enumerate(doc.get("sources", [])):
        kinds = [k for k in ("text", "file", "json", "records_file") if k in s]
        if len(kinds) != 1:
            raise ContractError(f"sources[{i}] needs exactly one of text / file / json / records_file")
    seen: set[str] = set()
    for i, a in enumerate(doc["assertions"]):
        if not isinstance(a, dict) or not a.get("question"):
            raise ContractError(f"assertions[{i}] needs a 'question'")
        unknown = set(a) - KNOWN_ASSERTION_KEYS
        if unknown:
            raise ContractError(f"assertions[{i}] has unknown keys {sorted(unknown)}; allowed: {sorted(KNOWN_ASSERTION_KEYS)}")
        if a.get("status") is not None and a["status"] not in STATUSES:
            raise ContractError(f"assertions[{i}].status must be one of {sorted(STATUSES)}")
        if "expected_answer" not in a and "status" not in a:
            raise ContractError(f"assertions[{i}] must state an expected_answer or a status")
        a.setdefault("id", f"a{i + 1}")
        if a["id"] in seen:
            raise ContractError(f"duplicate assertion id {a['id']!r}")
        seen.add(a["id"])
    doc["_base"] = str(base) if base else None
    return doc


def _resolve(base: Path, rel: str) -> Path:
    """A source file must live under the contract's directory or the current directory; anything else is refused."""
    roots = [base.resolve(), Path.cwd().resolve()]
    for root in roots:
        fp = (root / rel).resolve()
        if fp.exists() and any(r == fp or r in fp.parents for r in roots):
            return fp
    raise ContractError(f"source file {rel!r} not found under the contract directory or the working directory (paths outside them are refused)")


def _ingest(eng: MemoryOS, doc: dict) -> None:
    base = Path(doc["_base"]) if doc.get("_base") else Path.cwd()
    for s in doc.get("sources", []):
        kw: dict[str, Any] = {"user_id": s.get("user_id", "user"), "tenant_id": s.get("tenant_id", "default")}
        if "text" in s:
            eng.remember(s["text"], source_type=s.get("source_type", "user_statement"), effective_at=s.get("effective_at"), origin=s.get("origin"), **kw)
        elif "file" in s:
            fp = _resolve(base, s["file"])
            eng.remember(fp.read_text(encoding="utf-8"), source_type=s.get("source_type", "document"), origin=s.get("origin", s["file"]), **kw)
        elif "records_file" in s:
            fp = _resolve(base, s["records_file"])
            keep = tuple(s.get("fields", ("subject", "predicate", "object", "valid_from")))
            for rec in json.loads(fp.read_text(encoding="utf-8"))[s.get("records_key", "records")]:
                eng.remember_json({k: rec[k] for k in keep if k in rec}, origin=rec.get("source", s["records_file"]), **kw)
        else:
            eng.remember_json(s["json"], origin=s.get("origin"), **kw)


def _check(a: dict, r) -> tuple[list[str], str]:
    expected = a.get("status") or "answered"
    fails: list[str] = []
    if r.status != expected:
        fails.append(f"status is {r.status!r}, expected {expected!r}")
    ans = r.answer.lower() if r.supported else ""
    if a.get("expected_answer") is not None and str(a["expected_answer"]).lower() not in ans:
        fails.append(f"answer does not contain {a['expected_answer']!r}")
    if a.get("forbidden_answer") is not None and str(a["forbidden_answer"]).lower() in ans:
        fails.append(f"answer contains forbidden value {a['forbidden_answer']!r}")
    if a.get("require_evidence"):
        if not r.evidence:
            fails.append("no evidence returned")
        elif any(not e.source_id for e in r.evidence):
            fails.append("an evidence item has no source id")
        elif a.get("expected_answer") is not None and not any(str(a["expected_answer"]).lower() in e.excerpt.lower() for e in r.evidence):
            fails.append("no evidence excerpt contains the expected answer")
    if a.get("require_temporal_evidence") and not (any(e.effective_at for e in r.evidence) or r.confidence.temporal_validity in ("current", "historical")):
        fails.append("no temporal evidence (effective date or current/historical validity)")
    if a.get("max_context_tokens") is not None and r.context_tokens > a["max_context_tokens"]:
        fails.append(f"used {r.context_tokens} context tokens, budget {a['max_context_tokens']}")
    return fails, expected


def run_contract(doc: dict, *, settings: Settings | None = None, embedder=None) -> SuiteResult:
    """Run a validated contract in a fresh in-memory engine so runs never see each other's state."""
    cfg = settings or Settings(**doc.get("settings", {}))
    kw = {"embedder": embedder} if embedder is not None else {}
    eng = MemoryOS.in_memory(settings=cfg, **kw)
    try:
        _ingest(eng, doc)
        out: list[AssertionResult] = []
        for a in doc["assertions"]:
            r = eng.recall(a["question"], user_id=a.get("user_id", "user"), tenant_id=a.get("tenant_id", "default"), as_of=a.get("as_of"), use_cache=False)
            fails, expected = _check(a, r)
            out.append(AssertionResult(a["id"], a["question"], not fails, fails, r.status, r.answer if r.supported else "", expected, r.strategy, r.context_tokens, r.latency_ms, expected == "answered"))
        return SuiteResult(doc["suite"], out, {"answerability": cfg.answerability, "embedder": eng.embedder.name})
    finally:
        eng.close()


def compare(baseline: dict, current: dict) -> dict:
    """What changed between two ``SuiteResult.to_dict()`` runs of the same contract."""
    b = {r["id"]: r for r in baseline["results"]}
    c = {r["id"]: r for r in current["results"]}
    both = [i for i in c if i in b]
    regressions = [{"id": i, "question": c[i]["question"], "failures": c[i]["failures"]} for i in both if b[i]["passed"] and not c[i]["passed"]]
    fixed = [i for i in both if not b[i]["passed"] and c[i]["passed"]]
    status_changed = [{"id": i, "from": b[i]["status"], "to": c[i]["status"]} for i in both if b[i]["status"] != c[i]["status"]]
    answer_changed = [{"id": i, "from": b[i]["answer"], "to": c[i]["answer"]} for i in both if b[i]["status"] == c[i]["status"] == "answered" and b[i]["answer"] != c[i]["answer"]]
    worse_abstention = [i for i in both if c[i]["answerable"] and b[i]["status"] == "answered" and c[i]["status"] != "answered"]
    false_answers = [i for i in both if not c[i]["answerable"] and c[i]["status"] == "answered" and b[i]["status"] != "answered"]
    return {
        "suite": current["suite"], "regressions": regressions, "fixed": fixed, "status_changed": status_changed, "answer_changed": answer_changed,
        "abstention_worse": worse_abstention, "new_unsupported_answers": false_answers,
        "assertions_added": [i for i in c if i not in b], "assertions_removed": [i for i in b if i not in c],
        "mean_context_tokens_delta": round(current["mean_context_tokens"] - baseline["mean_context_tokens"], 2),
        "mean_latency_ms_delta": round(current["mean_latency_ms"] - baseline["mean_latency_ms"], 2),
        "ok": not regressions and not worse_abstention and not false_answers,
    }


def render(result: dict, diff: dict | None = None) -> str:
    L = [f"Memory CI: suite {result['suite']!r} ({result['config'].get('answerability')}, {result['config'].get('embedder')})",
         f"  {result['assertions'] - result['failed']}/{result['assertions']} assertions passed; mean {result['mean_context_tokens']:.0f} context tokens, {result['mean_latency_ms']:.1f} ms"]
    for r in result["results"]:
        L.append(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['id']}: {r['question']}")
        for f in r["failures"]:
            L.append(f"        - {f}")
    if diff:
        L.append("Regression report against baseline:")
        for key, label in (("regressions", "expectations that now fail"), ("abstention_worse", "answerable questions now refused"), ("new_unsupported_answers", "questions that must be refused but are now answered")):
            items = diff[key]
            L.append(f"  {label}: {len(items)}" + ("" if not items else " -> " + ", ".join(i["id"] if isinstance(i, dict) else i for i in items)))
        L.append(f"  fixed: {len(diff['fixed'])}; status changes: {len(diff['status_changed'])}; answer text changes: {len(diff['answer_changed'])}")
        L.append(f"  mean context tokens {diff['mean_context_tokens_delta']:+}, mean latency {diff['mean_latency_ms_delta']:+} ms")
        L.append("  verdict: " + ("no regression" if diff["ok"] else "REGRESSION"))
    return "\n".join(L)
