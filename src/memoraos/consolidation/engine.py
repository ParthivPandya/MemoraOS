"""Autonomous memory consolidation. Originals are never modified or deleted.

Consolidation only *adds* derived, low-reliability summary memories (each linked to its sources),
marks near-duplicates by reference, and records conservative alias merges. Derived memories carry no
facts, so consolidation can never overwrite a newer verified fact with an older inferred one.
Every run is stored with a report and can be rolled back.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from typing import TYPE_CHECKING

import numpy as np

from ..models import Scope
from ..providers.local import split_sentences
from ..retrieval.facts import load_facts
from ..store import content_hash
from ..truth.timeline import build_timeline
from ..util import STOPWORDS, content_terms, parse_ts, stem, tokenize

if TYPE_CHECKING:
    from ..engine import MemoryOS

MAX_MEMORIES = 5000
SUMMARY_SENTENCES = 3


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


class Consolidator:
    def __init__(self, engine: MemoryOS):
        self.e = engine
        self.db = engine.db
        self.store = engine.store
        self.settings = engine.settings

    # ------------------------------------------------------------------ run
    def run(self, scope: Scope, *, mode: str = "manual", dry_run: bool = False) -> dict:
        tenant, user = scope.tenant_id, scope.user_id
        rows = self.db.query(
            "SELECT m.rowid AS rid, m.* FROM memories m WHERE m.tenant_id=? AND m.user_id=? AND m.scope_level='user'"
            " AND m.status='active' AND m.derived=0 ORDER BY m.rowid LIMIT ?",
            (tenant, user, MAX_MEMORIES),
        )
        watermark_row = self.db.one(
            "SELECT MAX(watermark) FROM consolidation_runs WHERE tenant_id=? AND user_id=? AND status='completed' AND rolled_back_at IS NULL AND mode != 'dry_run'",
            (tenant, user),
        )
        last_mark = int(watermark_row[0] or 0)
        new_mark = max((r["rid"] for r in rows), default=last_mark)
        incremental = mode == "incremental"
        new_ids = {r["id"] for r in rows if r["rid"] > last_mark} if incremental else {r["id"] for r in rows}
        report: dict = {
            "mode": "dry_run" if dry_run else mode, "examined": len(rows), "new_since_last_run": len(new_ids),
            "near_duplicates": [], "alias_merges": [], "alias_candidates": [], "clusters": [], "created_memory_ids": [],
            "superseded_summary_ids": [], "corroborated_facts": [], "outdated_values": [], "importance_updated": 0,
            "originals_modified": 0,
        }
        if not rows or (incremental and not new_ids):
            return self._finish(scope, report, new_mark, persist=False)

        ids = [r["id"] for r in rows]
        vecs = self.store.embed_texts([r["normalized_content"] for r in rows])
        tokens = {r["id"]: {stem(t) for t in tokenize(r["normalized_content"]) if t not in STOPWORDS} for r in rows}
        by_id = {r["id"]: r for r in rows}

        # 1. near-duplicates (the newer memory points at the older one)
        sims = vecs @ vecs.T
        marked: list[tuple[str, str]] = []
        for j in range(len(ids)):
            for i in range(j):
                if sims[i, j] >= self.settings.near_duplicate_cosine and _jaccard(tokens[ids[i]], tokens[ids[j]]) >= self.settings.near_duplicate_jaccard:
                    if by_id[ids[i]]["content_hash"] != by_id[ids[j]]["content_hash"] and not by_id[ids[j]]["duplicate_of"] and (not incremental or ids[j] in new_ids or ids[i] in new_ids):
                        marked.append((ids[j], ids[i]))
                        break
        report["near_duplicates"] = [{"duplicate": d, "canonical": c} for d, c in marked]

        # 2. entity resolution (conservative)
        merges, candidates = self._alias_proposals(scope)
        report["alias_merges"], report["alias_candidates"] = merges, candidates

        # 3. clusters -> derived summaries
        clusters = self._clusters(rows, vecs, tokens, sims)
        to_create = []
        for cl in clusters:
            if incremental and not (set(cl["members"]) & new_ids):
                continue
            key = content_hash(",".join(sorted(cl["members"])))
            existing = self.db.query(
                "SELECT id, metadata FROM memories WHERE tenant_id=? AND user_id=? AND derived=1 AND status='active'", (tenant, user)
            )
            same = [e for e in existing if json.loads(e["metadata"]).get("cluster_label") == cl["label"]]
            if any(json.loads(e["metadata"]).get("cluster_key") == key for e in same):
                continue
            cl["key"], cl["supersedes"] = key, [e["id"] for e in same]
            to_create.append(cl)
        report["clusters"] = [{"label": c["label"], "size": len(c["members"]), "members": c["members"], "supersedes": c["supersedes"]} for c in to_create]

        # 4. analytics that do not change data
        facts = load_facts(self.db, scope)
        seen: Counter[tuple[str, str, str]] = Counter()
        slots: dict[tuple[str, str], list] = {}
        for f in facts:
            seen[(f.subject_key, f.predicate, f.object_key)] += 1
            if f.slot:
                slots.setdefault((f.subject_key, f.slot), []).append(f)
        report["corroborated_facts"] = [{"subject": s, "predicate": p, "object": o, "assertions": n} for (s, p, o), n in seen.items() if n > 1]
        for (s, slot), fs in slots.items():
            if len({f.object_key for f in fs}) > 1:
                tl = build_timeline(fs)
                if not tl.groups[-1].conflicted:
                    older = [r.value for g in tl.groups[:-1] for r in g.runs]
                    report["outdated_values"].append({"subject": s, "slot": slot, "current": [r.value for r in tl.groups[-1].runs], "superseded": older})

        if dry_run:
            return self._finish(scope, report, new_mark)

        with self.db.tx() as conn:
            for dup, canon in marked:
                conn.execute("UPDATE memories SET duplicate_of=? WHERE id=?", (canon, dup))
                conn.execute("INSERT OR IGNORE INTO memory_links(src_id,dst_id,type,run_id,tenant_id,created_at) VALUES(?,?,?,?,?,?)", (dup, canon, "near_duplicate", None, tenant, self.store.now()))
            run_id = self.e.new_id("run")
            for a, b in ((m["alias"], m["canonical"]) for m in merges):
                conn.execute(
                    "INSERT OR REPLACE INTO aliases(alias_key, canonical_key, run_id, tenant_id, user_id, scope_level, scope_id, active, created_at) VALUES(?,?,?,?,?,?,?,1,?)",
                    (a, b, run_id, tenant, user, "user", user, self.store.now()),
                )
            for cl in to_create:
                for old in cl["supersedes"]:
                    conn.execute("UPDATE memories SET status='inactive' WHERE id=?", (old,))
                    report["superseded_summary_ids"].append(old)
                mid = self._write_summary(conn, scope, cl, by_id, run_id)
                report["created_memory_ids"].append(mid)
            report["importance_updated"] = self._importance(conn, rows, facts)
            report["run_id"] = run_id
            report["duplicate_ids_marked"] = [d for d, _ in marked]
            self.store.append_event(conn, tenant, user, "consolidation.run", None, {"run_id": run_id, "created": len(report["created_memory_ids"]), "duplicates": len(marked), "aliases": len(merges)})
        self.e.vectors.invalidate()
        return self._finish(scope, report, new_mark, run_id=run_id)

    def _finish(self, scope: Scope, report: dict, watermark: int, *, run_id: str | None = None, persist: bool = True) -> dict:
        rid = run_id or report.get("run_id") or self.e.new_id("run")
        report["run_id"] = rid
        if persist:
            mark = 0 if report["mode"] == "dry_run" else watermark
            self.db.execute(
                "INSERT OR REPLACE INTO consolidation_runs(id, ts, tenant_id, user_id, mode, status, watermark, report) VALUES(?,?,?,?,?,?,?,?)",
                (rid, self.store.now(), scope.tenant_id, scope.user_id, report["mode"], "completed", mark, json.dumps(report, default=str)),
            )
        return report

    # ------------------------------------------------------------------ pieces
    def _alias_proposals(self, scope: Scope) -> tuple[list[dict], list[dict]]:
        rows = self.db.query(
            "SELECT entity_key, entity_name, memory_id FROM mentions WHERE tenant_id=? AND user_id=? AND scope_level='user'", (scope.tenant_id, scope.user_id)
        )
        mem_of: dict[str, set[str]] = {}
        for r in rows:
            mem_of.setdefault(r["entity_key"], set()).add(r["memory_id"])
        existing = {r["alias_key"] for r in self.db.query("SELECT alias_key FROM aliases WHERE tenant_id=? AND user_id=? AND active=1", (scope.tenant_id, scope.user_id))}
        keys = sorted(mem_of)
        merges, candidates = [], []
        for short in keys:
            if " " in short or short in existing or short == "user":
                continue
            longs = [k for k in keys if k != short and k.split()[0] == short and len(k.split()) == 2]
            if not longs:
                continue
            entry = {"alias": short, "canonical": longs[0], "reason": "single token equals the first name of exactly one two-token entity"}
            co_mentioned = any(mem_of[short] & mem_of[k] for k in longs)
            if len(longs) == 1 and not co_mentioned:
                merges.append(entry)
            else:
                candidates.append(entry | {"reason": "ambiguous or co-mentioned; not merged automatically"})
        return merges, candidates

    def _clusters(self, rows, vecs: np.ndarray, tokens: dict[str, set[str]], sims: np.ndarray) -> list[dict]:
        min_size = self.settings.cluster_min_size
        ids = [r["id"] for r in rows]
        ent_rows = self.db.query(
            "SELECT entity_key, entity_name, memory_id FROM mentions WHERE tenant_id=? AND user_id=? AND scope_level='user'",
            (rows[0]["tenant_id"], rows[0]["user_id"]),
        ) if rows else []
        by_entity: dict[str, set[str]] = {}
        names: dict[str, str] = {}
        valid = set(ids)
        for r in ent_rows:
            if r["memory_id"] in valid:
                by_entity.setdefault(r["entity_key"], set()).add(r["memory_id"])
                names.setdefault(r["entity_key"], r["entity_name"])
        out: list[dict] = []
        covered: set[str] = set()
        for key, mems in sorted(by_entity.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            if len(mems) >= min_size:
                out.append({"label": f"entity:{key}", "title": names[key], "members": sorted(mems, key=ids.index), "kind": "entity"})
                covered |= mems
        # theme clusters: connected components of the similarity graph among memories not already clustered
        free = [i for i, mid in enumerate(ids) if mid not in covered]
        parent = {i: i for i in free}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a_i, a in enumerate(free):
            for b in free[a_i + 1 :]:
                if sims[a, b] >= self.settings.cluster_cosine:
                    parent[find(a)] = find(b)
        comps: dict[int, list[int]] = {}
        for i in free:
            comps.setdefault(find(i), []).append(i)
        for comp in comps.values():
            if len(comp) >= min_size:
                common = Counter(t for i in comp for t in tokens[ids[i]])
                label_terms = [t for t, _ in common.most_common(3)]
                out.append({"label": "theme:" + "-".join(sorted(label_terms)), "title": " / ".join(label_terms), "members": [ids[i] for i in comp], "kind": "theme"})
        for cl in out:
            cl["vecs"] = {mid: vecs[ids.index(mid)] for mid in cl["members"]}
        return out

    def _write_summary(self, conn, scope: Scope, cl: dict, by_id: dict, run_id: str) -> str:
        members = cl["members"]
        centroid = np.mean([cl["vecs"][m] for m in members], axis=0)
        sentences: list[tuple[float, str, str]] = []
        terms = content_terms(cl["title"]) if cl["kind"] == "theme" else content_terms(cl["title"])
        for m in members:
            for s in split_sentences(by_id[m]["original_content"]):
                v = self.store.embed_texts([s])[0]
                sentences.append((float(v @ centroid) + 0.1 * len(set(content_terms(s)) & set(terms)), s, m))
        sentences.sort(key=lambda x: (-x[0], x[1]))
        picked, seen = [], set()
        for _, s, m in sentences:
            if s.lower() in seen:
                continue
            seen.add(s.lower())
            picked.append((s, m))
            if len(picked) >= SUMMARY_SENTENCES:
                break
        dates = sorted(by_id[m]["effective_at"] or by_id[m]["created_at"] for m in members)
        text = (
            f"Consolidated summary of {len(members)} memories about {cl['title']} ({dates[0][:10]} to {dates[-1][:10]}). "
            + " ".join(s if s.endswith((".", "!", "?")) else s + "." for s, _ in picked)
        )
        sid = self.store.insert_source(
            conn, scope, "user", source_type="consolidation", origin=f"consolidation:{run_id}", content=text, reliability=0.3,
            verification="unverified", metadata={"run_id": run_id, "members": members},
        )
        vec = self.store.embed_texts([text])[0]
        mid = self.store.insert_memory(
            conn, scope, "user", source_id=sid, chunk_index=0, original=text, category="semantic", confidence=0.5, effective_at=None,
            derived=True, metadata={"cluster_key": cl["key"], "cluster_label": cl["label"], "run_id": run_id, "members": members}, vector=vec,
        )
        for m in members:
            conn.execute("INSERT OR IGNORE INTO memory_links(src_id,dst_id,type,run_id,tenant_id,created_at) VALUES(?,?,?,?,?,?)", (mid, m, "derived_from", run_id, scope.tenant_id, self.store.now()))
        ent = cl["label"].split(":", 1)[1] if cl["kind"] == "entity" else None
        if ent:
            self.store.insert_mentions(conn, scope, "user", mid, {ent: cl["title"]})
        self.store.append_event(conn, scope.tenant_id, scope.user_id, "consolidation.summary_created", mid, {"run_id": run_id, "members": len(members)})
        return mid

    def _importance(self, conn, rows, facts) -> int:
        fact_counts = Counter(f.memory_id for f in facts)
        now = self.e.clock()
        n = 0
        for r in rows:
            age_days = max(0.0, (now - parse_ts(r["created_at"])).total_seconds() / 86400)
            imp = (
                0.3 * min(1.0, r["access_count"] / 10) + 0.3 * min(1.0, (r["mention_count"] - 1) / 5)
                + 0.2 * min(1.0, fact_counts.get(r["id"], 0) / 5) + 0.2 / (1 + age_days / 30)
            )
            conn.execute("UPDATE memories SET importance=? WHERE id=?", (round(imp, 4), r["id"]))
            n += 1
        return n

    # ------------------------------------------------------------------ rollback
    def rollback(self, run_id: str, *, tenant_id: str, user_id: str) -> dict:
        row = self.db.one("SELECT * FROM consolidation_runs WHERE id=? AND tenant_id=? AND user_id=?", (run_id, tenant_id, user_id))
        if not row:
            from ..engine import NotFoundError

            raise NotFoundError(run_id)
        if row["rolled_back_at"]:
            return {"run_id": run_id, "already_rolled_back": True}
        rep = json.loads(row["report"])
        with self.db.tx() as conn:
            for mid in rep.get("created_memory_ids", []):
                self.store.delete_memory_rows(conn, mid)
            for old in rep.get("superseded_summary_ids", []):
                conn.execute("UPDATE memories SET status='active' WHERE id=? AND derived=1", (old,))
            for dup in rep.get("duplicate_ids_marked", []):
                conn.execute("UPDATE memories SET duplicate_of=NULL WHERE id=?", (dup,))
                conn.execute("DELETE FROM memory_links WHERE src_id=? AND type='near_duplicate'", (dup,))
            conn.execute("DELETE FROM aliases WHERE run_id=?", (run_id,))
            conn.execute("UPDATE consolidation_runs SET rolled_back_at=? WHERE id=?", (self.store.now(), run_id))
            self.store.append_event(conn, tenant_id, user_id, "consolidation.rollback", None, {"run_id": run_id})
        self.e.vectors.invalidate()
        return {"run_id": run_id, "removed_summaries": len(rep.get("created_memory_ids", [])), "restored_summaries": len(rep.get("superseded_summary_ids", [])), "unmarked_duplicates": len(rep.get("duplicate_ids_marked", []))}


class ConsolidationScheduler:
    """Runs incremental consolidation on an interval in a daemon thread."""

    def __init__(self, engine: MemoryOS, user_id: str, tenant_id: str, interval: float):
        self.engine, self.user_id, self.tenant_id, self.interval = engine, user_id, tenant_id, interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.runs = 0
        self.last_error: str | None = None

    def run_once(self) -> dict:
        report = self.engine.consolidate(user_id=self.user_id, tenant_id=self.tenant_id, mode="incremental")
        self.runs += 1
        return report

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - a failed run must not kill the scheduler
                self.last_error = str(exc)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="memoraos-consolidation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


def reflect_report(engine: MemoryOS, scope: Scope, topic: str | None) -> dict:
    db = engine.db
    from ..storage.visibility import visibility_clause

    vis, params = visibility_clause(scope, "m")
    mems = db.query(f"SELECT m.id, m.original_content, m.category, m.derived FROM memories m WHERE m.status='active' AND {vis}", params)
    terms = content_terms(topic) if topic else []
    if terms:
        mems = [m for m in mems if set(terms) <= {stem(t) for t in tokenize(m["original_content"])}]
    ids = {m["id"] for m in mems}
    entity_counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for r in db.query(f"SELECT n.entity_key, n.entity_name, n.memory_id FROM mentions n WHERE {visibility_clause(scope, 'n')[0]}", visibility_clause(scope, "n")[1]):
        if r["memory_id"] in ids:
            entity_counts[r["entity_key"]] += 1
            names.setdefault(r["entity_key"], r["entity_name"])
    term_counts: Counter[str] = Counter(t for m in mems if not m["derived"] for t in content_terms(m["original_content"]))
    contradictions = engine.contradictions(user_id=scope.user_id, tenant_id=scope.tenant_id, **{k: v for k, v in scope.model_dump().items() if k in ("agent_id", "session_id", "project_id")})
    return {
        "topic": topic, "memories_considered": len(mems),
        "by_category": dict(Counter(m["category"] for m in mems)),
        "recurring_entities": [{"entity": names[k], "memories": n} for k, n in entity_counts.most_common(10)],
        "recurring_terms": [{"term": t, "count": n} for t, n in term_counts.most_common(10)],
        "open_conflicts": [c.model_dump() for c in contradictions if not c.resolved],
        "version_changes": [c.model_dump() for c in contradictions if c.resolved],
        "generated_at": engine.store.now(),
    }
