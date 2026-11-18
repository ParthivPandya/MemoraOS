"""Public-benchmark adapters, retrieval only: LongMemEval and LoCoMo.

Only the RETRIEVAL step is measured, so no LLM, API key or judge is involved and the numbers are reproducible:
does the evidence a system returns come from the session (LongMemEval) or dialogue turn (LoCoMo) that the dataset
authors marked as containing the answer? This is NOT the datasets' answer-accuracy metric and must not be compared to
published QA scores.

The datasets are third-party, downloaded locally into data/external/ and never redistributed (LoCoMo is CC BY-NC 4.0):

    python -m benchmarks.public longmemeval --n 60
    python -m benchmarks.public locomo
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from memoraos import MemoryOS
from memoraos.ingestion.classify import chunk_text
from memoraos.providers.embeddings import adapt_embedder
from memoraos.providers.local import HashingEmbedder
from memoraos.recall import Ctx
from memoraos.retrieval.fusion import rrf
from memoraos.retrieval.lexical import PyBM25
from memoraos.retrieval.vector import top_k_cosine
from memoraos.routing.router import analyze_query
from memoraos.util import utcnow

from .stats import wilson

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "external"
OUT = ROOT / "benchmarks" / "reports"
KS = (5, 10)
U = "bench_user"


class Unit:
    """One retrievable passage: its text and the id of the dataset item (session or turn) it belongs to."""

    def __init__(self, uid: str, text: str):
        self.uid, self.text = uid, text


def _units_to_chunks(units: list[Unit]) -> tuple[list[str], list[str]]:
    ids, texts = [], []
    for u in units:
        for c in chunk_text(u.text, 800, 100) or [u.text]:
            ids.append(u.uid)
            texts.append(c)
    return ids, texts


class Retrievers:
    """BM25, vector and hybrid baselines plus MemoraOS, over the same units; every method returns ranked unit ids."""

    def __init__(self, units: list[Unit], embedder=None):
        self.embedder = adapt_embedder(embedder or HashingEmbedder(512))
        self.unit_of, texts = _units_to_chunks(units)
        self.keys = [f"c{i}" for i in range(len(texts))]
        self.bm25 = PyBM25(dict(zip(self.keys, texts, strict=True)))
        self.mat = np.asarray(self.embedder.embed(texts), dtype=np.float32)
        self.mem = MemoryOS.in_memory(embedder=embedder)
        for u in units:
            self.mem.remember(u.text, user_id=U, source_type="document", origin=u.uid)
        rows = self.mem.db.query("SELECT m.id AS id, s.origin AS origin FROM memories m JOIN sources s ON s.id = m.source_id")
        self.mem_unit = {r["id"]: r["origin"] for r in rows}

    def _units(self, keys: list[str]) -> list[str]:
        return [self.unit_of[int(k[1:])] for k in keys]

    def search(self, system: str, q: str, k: int) -> list[str]:
        if system == "memoraos_recall":
            res = self.mem.recall(q, user_id=U, top_k=k, use_cache=False)
            return [self.mem_unit.get(e.memory_id, "") for e in res.evidence]
        if system == "memoraos_retriever":
            r = self.mem.recaller
            ctx = Ctx(self.mem.scope_for(U), q, analyze_query(q, utcnow()), None, k, self.mem.store.now())
            return [self.mem_unit.get(c.memory_id, "") for c in r.hybrid(ctx, k)]
        pool = 50
        if system == "bm25":
            return self._units([c.memory_id for c in self.bm25.search(q, k)])
        qv = np.asarray(self.embedder.embed([q]), dtype=np.float32)[0]
        vec = top_k_cosine(self.keys, self.mat, qv, pool if system == "hybrid_rag" else k, min_score=-1.0)
        if system == "vector":
            return self._units([c.memory_id for c in vec])
        fused = rrf({"bm25": self.bm25.search(q, pool), "vector": vec}, k=60)
        return self._units([c.memory_id for c in fused[:k]])

    def close(self) -> None:
        self.mem.close()


SYSTEMS = ["bm25", "vector", "hybrid_rag", "memoraos_retriever", "memoraos_recall"]


def _distinct(ids: list[str], k: int) -> list[str]:
    return list(dict.fromkeys(i for i in ids if i))[:k]


def score(hits: dict[str, dict[int, list[bool]]], extra: dict | None = None) -> dict:
    rows = {}
    for system, per_k in hits.items():
        rows[system] = {}
        for k, flags in per_k.items():
            n, s = len(flags), sum(flags)
            lo, hi = wilson(s, n)
            rows[system][f"hit@{k}"] = {"hits": s, "n": n, "rate": round(s / n, 4) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}
    return rows


def _paired(hits: dict[str, dict[int, list[bool]]], a: str, b: str, k: int) -> dict:
    fa, fb = hits[a][k], hits[b][k]
    return {"a": a, "b": b, "k": k, "a_only": sum(x and not y for x, y in zip(fa, fb, strict=True)), "b_only": sum(y and not x for x, y in zip(fa, fb, strict=True))}


def longmemeval(n: int, seed: int, embedder=None, path: Path | None = None) -> dict:
    path = path or DATA / "longmemeval_s_cleaned.json"
    if not path.is_file():
        raise SystemExit(f"{path} not found. Download longmemeval_s_cleaned.json from https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned into data/external/")
    data = [q for q in json.loads(path.read_text(encoding="utf-8")) if not str(q["question_id"]).endswith("_abs")]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for q in data:
        by_type[q["question_type"]].append(q)
    rng = random.Random(seed)
    for v in by_type.values():
        rng.shuffle(v)
    sample: list[dict] = []
    while len(sample) < n and any(by_type.values()):
        for t in sorted(by_type):
            if by_type[t] and len(sample) < n:
                sample.append(by_type[t].pop())
    hits = {s: {k: [] for k in KS} for s in SYSTEMS}
    per_type: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    t0 = time.perf_counter()
    for i, q in enumerate(sample, 1):
        units = [Unit(sid, "\n".join(f"{t['role']}: {t['content']}" for t in turns)) for sid, turns in zip(q["haystack_session_ids"], q["haystack_sessions"], strict=True)]
        gold = set(q["answer_session_ids"])
        r = Retrievers(units, embedder)
        for s in SYSTEMS:
            ranked = r.search(s, q["question"], 10 * 5)
            for k in KS:
                ok = bool(gold & set(_distinct(ranked, k)))
                hits[s][k].append(ok)
                per_type[s][q["question_type"]].append(ok) if k == 5 else None
        r.close()
        print(f"  {i}/{len(sample)} {time.perf_counter() - t0:.0f}s", flush=True)
    return {
        "dataset": "LongMemEval (longmemeval_s_cleaned.json), non-abstention questions", "metric": "session hit@k: an answer-bearing session is among the sessions of the top-k retrieved chunks",
        "questions": len(sample), "seed": seed, "embedder": (embedder.name if embedder else "hashing"), "unit": "session (chunked to 800 chars)",
        "systems": score(hits), "per_type_hit@5": {s: {t: f"{sum(v)}/{len(v)}" for t, v in d.items()} for s, d in per_type.items()},
        "paired_hit@5": _paired(hits, "memoraos_retriever", "hybrid_rag", 5), "seconds": round(time.perf_counter() - t0),
    }


def locomo(embedder=None, path: Path | None = None, limit: int | None = None) -> dict:
    path = path or DATA / "locomo10.json"
    if not path.is_file():
        raise SystemExit(f"{path} not found. Download data/locomo10.json from https://github.com/snap-research/locomo into data/external/")
    convs = json.loads(path.read_text(encoding="utf-8"))[:limit]
    hits_any = {s: {k: [] for k in KS} for s in SYSTEMS}
    hits_all = {s: {k: [] for k in KS} for s in SYSTEMS}
    t0 = time.perf_counter()
    skipped = 0
    for ci, conv in enumerate(convs, 1):
        c = conv["conversation"]
        units = []
        for key in sorted((k for k in c if k.startswith("session_") and isinstance(c[k], list)), key=lambda x: int(x.split("_")[1])):
            date = c.get(f"{key}_date_time", "")
            for turn in c[key]:
                units.append(Unit(turn["dia_id"], f"[{date}] {turn['speaker']}: {turn['text']}"))
        r = Retrievers(units, embedder)
        known = {u.uid for u in units}
        for qa in conv["qa"]:
            if qa.get("category") == 5 or not qa.get("evidence"):
                skipped += 1  # adversarial (no answer) or unlabeled questions have no gold turn
                continue
            gold = {e.strip() for part in qa["evidence"] for e in part.split(";") if e.strip()} & known
            if not gold:
                skipped += 1
                continue
            for s in SYSTEMS:
                ranked = r.search(s, qa["question"], 10 * 3)
                for k in KS:
                    got = set(_distinct(ranked, k))
                    hits_any[s][k].append(bool(gold & got))
                    hits_all[s][k].append(gold <= got)
        r.close()
        print(f"  conversation {ci}/{len(convs)} {time.perf_counter() - t0:.0f}s", flush=True)
    return {
        "dataset": "LoCoMo (locomo10.json), categories 1-4 with labelled evidence turns", "license_note": "CC BY-NC 4.0 data, downloaded locally and not redistributed",
        "metric": "any-hit@k: at least one gold turn in the top-k; all-hit@k: every gold turn in the top-k", "questions": len(hits_any["bm25"][5]), "skipped_unlabelled_or_adversarial": skipped,
        "embedder": (embedder.name if embedder else "hashing"), "unit": "dialogue turn",
        "any_hit": score(hits_any), "all_hit": score(hits_all), "paired_any_hit@5": _paired(hits_any, "memoraos_retriever", "hybrid_rag", 5), "seconds": round(time.perf_counter() - t0),
    }


def render(name: str, res: dict) -> str:
    lines = [f"# {name} retrieval-only results", "", "Generated by `python -m benchmarks.public`. Do not edit.", "", f"- Dataset: {res['dataset']}", f"- Metric: {res['metric']}", f"- Questions: {res['questions']}", f"- Embedder: {res['embedder']}; retrieval unit: {res['unit']}",
             "- This measures retrieval only. It is not the dataset's answer-accuracy metric and is not comparable to published QA scores.", ""]
    blocks = {"systems": res.get("systems")} if "systems" in res else {"any-hit": res["any_hit"], "all-hit": res["all_hit"]}
    for title, rows in blocks.items():
        lines += [f"## {title}", "", "| system | " + " | ".join(f"@{k}" for k in KS) + " |", "|---|" + "---:|" * len(KS)]
        for s, d in rows.items():
            lines.append(f"| {s} | " + " | ".join(f"{d[f'hit@{k}']['hits']}/{d[f'hit@{k}']['n']} = {d[f'hit@{k}']['rate']:.1%} [{d[f'hit@{k}']['ci95'][0]:.0%}, {d[f'hit@{k}']['ci95'][1]:.0%}]" for k in KS) + " |")
        lines.append("")
    p = res.get("paired_hit@5") or res.get("paired_any_hit@5")
    lines += [f"Paired at k=5, {p['a']} vs {p['b']}: {p['a_only']} questions only the first hit, {p['b_only']} only the second.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["longmemeval", "locomo"])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--limit", type=int, default=None, help="locomo: number of conversations")
    ap.add_argument("--embedder", default="")
    a = ap.parse_args(argv)
    emb = None
    tag = ""
    if a.embedder:
        from memoraos.providers.embeddings import SentenceTransformerEmbedder

        emb, tag = SentenceTransformerEmbedder(a.embedder), "_" + a.embedder.split("/")[-1]
    res = longmemeval(a.n, a.seed, emb) if a.which == "longmemeval" else locomo(emb, limit=a.limit)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"public_{a.which}{tag}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (OUT / f"PUBLIC_{a.which.upper()}{tag}.md").write_text(render(a.which, res), encoding="utf-8")
    print(render(a.which, res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
