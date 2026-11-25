"""Portable memory bundles: one JSON file holding a user's active memories, their facts and explicit causal links.

This is MemoraOS's own format (``format: "memoraos-bundle"``); it is not an implementation of any other tool's
interchange format. What round-trips: memory text, effective time, source type, origin,
verification state, metadata, active facts and causal links. What does not: ids (new ones are
assigned), creation times (kept in metadata as ``original_created_at``), retracted facts, version history (exported
as read-only ``history``), recall logs, the audit chain and embeddings (recomputed on import).

Integrity: ``sha256`` covers the canonical content, so accidental damage or edits are detected. It is not
authentication, because anyone can recompute it. An optional HMAC-SHA256 ``signature`` (key from the environment,
never a command-line argument) authenticates the bundle for people who share the key. Without a verified signature
an import never keeps the ``verified`` label: it is downgraded to ``unverified``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from . import __version__
from .engine import MemoryOS
from .models import SOURCE_RELIABILITY

FORMAT = "memoraos-bundle"
VERSION = 1
KEY_ENV = "MEMORAOS_BUNDLE_KEY"
MAX_BYTES = 256 * 1024 * 1024
_VERIFICATIONS = ("unverified", "verified", "disputed", "hypothesis")


class BundleError(ValueError):
    pass


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _sign(payload: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def export_bundle(engine: MemoryOS, path: str | Path, *, user_id: str, tenant_id: str = "default", key: str | None = None) -> dict:
    """Write the user's active, non-derived memories to ``path``. Returns a short report."""
    rows = engine.db.query(
        "SELECT m.id, m.original_content, m.effective_at, m.created_at, m.category, m.metadata, m.version, s.source_type, s.origin,"
        " s.verification, s.reliability FROM memories m JOIN sources s ON s.id = m.source_id"
        " WHERE m.tenant_id=? AND m.user_id=? AND m.status='active' AND m.derived=0 ORDER BY m.created_at, m.rowid",
        (tenant_id, user_id),
    )
    ids = [r["id"] for r in rows]
    facts: dict[str, list[dict]] = {i: [] for i in ids}
    history: dict[str, list[dict]] = {i: [] for i in ids}
    links = []
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        marks = ",".join("?" * len(batch))
        for f in engine.db.query(
            f"SELECT memory_id, subject, predicate, object, valid_from, valid_until FROM facts WHERE memory_id IN ({marks}) AND retracted_at IS NULL"
            " ORDER BY recorded_at, rowid", batch,
        ):
            facts[f["memory_id"]].append({k: f[k] for k in ("subject", "predicate", "object", "valid_from", "valid_until")})
        for v in engine.db.query(
            f"SELECT memory_id, version, original_content, changed_at, reason FROM memory_versions WHERE memory_id IN ({marks}) ORDER BY version", batch,
        ):
            history[v["memory_id"]].append({k: v[k] for k in ("version", "original_content", "changed_at", "reason")})
        for lk in engine.db.query(
            f"SELECT src_id, dst_id, type FROM memory_links WHERE type LIKE 'causal:%' AND tenant_id=? AND src_id IN ({marks})", [tenant_id, *batch],
        ):
            if lk["dst_id"] in facts:
                links.append({"src": lk["src_id"], "dst": lk["dst_id"], "kind": lk["type"].split(":", 1)[1]})
    memories = [
        {
            "id": r["id"], "content": r["original_content"], "effective_at": r["effective_at"], "created_at": r["created_at"],
            "category": r["category"], "source_type": r["source_type"], "origin": r["origin"], "verification": r["verification"],
            "reliability": r["reliability"], "metadata": json.loads(r["metadata"] or "{}"), "version": r["version"],
            "facts": facts[r["id"]], "history": history[r["id"]],
        }
        for r in rows
    ]
    body = {"memories": memories, "links": sorted(links, key=lambda x: (x["src"], x["dst"], x["kind"]))}
    payload = _canonical(body)
    doc = {
        "format": FORMAT, "version": VERSION, "created_at": engine.store.now(), "memoraos_version": __version__,
        "source": {"user_id": user_id, "tenant_id": tenant_id}, **body, "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if key:
        doc["signature"] = {"alg": "hmac-sha256", "value": _sign(payload, key)}
    out = Path(path)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return {"path": str(out), "memories": len(memories), "facts": sum(len(m["facts"]) for m in memories), "links": len(links),
            "signed": bool(key), "sha256": doc["sha256"]}


def read_bundle(path: str | Path, *, key: str | None = None, require_signature: bool = False) -> tuple[dict, bool]:
    """Parse and verify a bundle. Returns ``(document, signature_verified)``; raises ``BundleError`` on any mismatch."""
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise BundleError("bundle is larger than the 256 MB limit")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BundleError(f"not valid JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise BundleError("not a memoraos bundle")
    if doc.get("version") != VERSION:
        raise BundleError(f"unsupported bundle version {doc.get('version')!r} (this build reads version {VERSION})")
    if not isinstance(doc.get("memories"), list) or not isinstance(doc.get("links"), list):
        raise BundleError("bundle has no memories/links lists")
    payload = _canonical({"memories": doc["memories"], "links": doc["links"]})
    if hashlib.sha256(payload).hexdigest() != doc.get("sha256"):
        raise BundleError("sha256 mismatch: the bundle was modified or damaged")
    sig = doc.get("signature")
    verified = False
    if sig:
        if key:
            if not hmac.compare_digest(_sign(payload, key), str(sig.get("value", ""))):
                raise BundleError("signature mismatch: wrong key, or the bundle was modified")
            verified = True
    if require_signature and not verified:
        raise BundleError("a verified signature is required but the bundle is unsigned or no key was given")
    return doc, verified


def import_bundle(
    engine: MemoryOS, path: str | Path, *, user_id: str, tenant_id: str = "default", key: str | None = None,
    require_signature: bool = False, dry_run: bool = False,
) -> dict:
    """Verify then import a bundle into ``user_id``'s memory. Re-importing the same bundle adds nothing new."""
    doc, verified = read_bundle(path, key=key, require_signature=require_signature)
    rep = {
        "memories": len(doc["memories"]), "imported": 0, "already_present": 0, "skipped": [], "facts": 0, "links": 0,
        "signature_verified": verified, "verified_downgraded": 0, "dry_run": dry_run, "bundle_sha256": doc["sha256"],
    }
    idmap: dict[str, str] = {}
    for m in doc["memories"]:
        if not isinstance(m, dict) or not isinstance(m.get("content"), str) or not m["content"].strip():
            rep["skipped"].append({"id": m.get("id") if isinstance(m, dict) else None, "reason": "no text content"})
            continue
        source_type = m.get("source_type") if m.get("source_type") in SOURCE_RELIABILITY else "external"
        verification = m.get("verification") if m.get("verification") in _VERIFICATIONS else "unverified"
        if verification == "verified" and not verified:
            verification = "unverified"
            rep["verified_downgraded"] += 1
        if dry_run:
            continue
        facts = [f for f in m.get("facts") or [] if isinstance(f, dict) and f.get("subject") and f.get("predicate") and f.get("object")]
        meta = dict(m.get("metadata") or {})
        meta.update({"imported_from_bundle": doc["sha256"][:16], "original_id": m.get("id"), "original_created_at": m.get("created_at")})
        res = engine.remember(
            m["content"], user_id=user_id, tenant_id=tenant_id, source_type=source_type, origin=m.get("origin") or "bundle",
            effective_at=m.get("effective_at"), verification=verification, metadata=meta,
            facts=facts or None, extract=False,
        )
        idmap[m.get("id")] = res.memory_ids[0]
        rep["already_present" if res.duplicate_of else "imported"] += 1
        rep["facts"] += 0 if res.duplicate_of else res.facts_recorded
    if not dry_run:
        for lk in doc["links"]:
            src, dst = idmap.get(lk.get("src")), idmap.get(lk.get("dst"))
            if src and dst and src != dst:
                try:
                    engine.link(src, dst, lk.get("kind"), user_id=user_id, tenant_id=tenant_id)
                    rep["links"] += 1
                except ValueError:
                    rep["skipped"].append({"link": lk, "reason": "invalid link kind"})
    return rep
