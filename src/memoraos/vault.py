"""Two-way sync between a folder of Markdown notes and a MemoraOS store.

Notes are imported as memories (original text kept, facts extracted as usual). Memories that did not come from the
vault are written to ``_memoraos/<id>.md`` so they can be read and edited as files. A small state file records, per
file, the hash of the file and of the memory text at the last sync, which is how a one-sided change is told apart from
a conflict. A conflict (both sides changed) is reported and left untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .engine import MemoryOS, NotFoundError
from .ingestion.classify import chunk_text

STATE_FILE = ".memoraos-sync.json"
EXPORT_DIR = "_memoraos"
_STATE_VERSION = 1


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading ``---`` block of ``key: value`` lines from the body. Anything else is returned as the body."""
    t = text.replace("\r\n", "\n")
    if t.startswith("---\n"):
        end = t.find("\n---\n", 3)
        if end != -1:
            meta: dict[str, str] = {}
            for line in t[4:end].split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            return meta, t[end + 5 :].lstrip("\n")
    return {}, text


def _render_export(rec: Any) -> str:
    head = (
        f"---\nmemoraos_id: {rec.id}\ncategory: {rec.category}\nsource: {rec.source_type}\n"
        f"verification: {rec.verification}\nrecorded: {rec.created_at}\n---\n\n"
    )
    return head + rec.original_content.strip("\n") + "\n"


def _load_state(vault: Path) -> dict:
    p = vault / STATE_FILE
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version") != _STATE_VERSION:
            raise ValueError(f"unsupported sync state version in {p}")
        return data
    return {"version": _STATE_VERSION, "files": {}}


def _save_state(vault: Path, state: dict) -> None:
    tmp = vault / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    os.replace(tmp, vault / STATE_FILE)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def sync_vault(
    mem: MemoryOS, vault: str | Path, *, user_id: str, tenant_id: str = "default",
    direction: str = "both", prune: bool = False, dry_run: bool = False,
) -> dict:
    """Sync ``vault`` with the user's memories. ``direction`` is ``import``, ``export`` or ``both``.

    Never overwrites when both sides changed. Deletions are only propagated with ``prune=True``: a note deleted from
    disk then hard-deletes its memories (``forget``), and the exported note of a memory that was forgotten is removed.
    Imported notes are never deleted from disk. Returns a report of what was (or, with ``dry_run``, would be) done.
    """
    if direction not in ("import", "export", "both"):
        raise ValueError("direction must be import, export or both")
    root = Path(vault)
    if not root.is_dir():
        raise ValueError(f"{root} is not a directory")
    state = _load_state(root)
    if state.get("user_id", user_id) != user_id or state.get("tenant_id", tenant_id) != tenant_id:
        raise ValueError("this vault was synced for a different user or tenant; use a separate vault")
    state["user_id"], state["tenant_id"] = user_id, tenant_id
    files: dict[str, dict] = state["files"]
    do_in, do_out = direction in ("import", "both"), direction in ("export", "both")
    rep: dict[str, Any] = {
        "dry_run": dry_run, "imported": [], "exported": [], "updated_from_file": [], "updated_from_memory": [],
        "conflicts": [], "missing_files": [], "missing_memories": [], "pruned": [], "skipped": [],
        "memory_changed_not_pushed": [], "unchanged": 0,
    }
    kw = {"user_id": user_id, "tenant_id": tenant_id}

    def mem_sha(ids: list[str]) -> str | None:
        parts = []
        for i in ids:
            try:
                r = mem.get(i, **kw)
            except NotFoundError:
                return None
            parts.append(f"{r.id}:{r.version}:{r.original_content}")
        return _sha("\n".join(parts))

    # 1. files already tracked
    for rel, ent in list(files.items()):
        path = root / rel
        ids: list[str] = ent["memory_ids"]
        cur_mem = mem_sha(ids)
        exists = path.is_file()
        if cur_mem is None:
            rep["missing_memories"].append(rel)
            if prune and do_out and ent["kind"] == "export" and exists:
                rep["pruned"].append(rel)
                if not dry_run:
                    path.unlink()
                    del files[rel]
            continue
        if not exists:
            rep["missing_files"].append(rel)
            if prune and (do_in if ent["kind"] == "import" else do_out):
                rep["pruned"].append(rel)
                if not dry_run:
                    if not ent.get("shared"):
                        for i in ids:
                            mem.forget(i, **kw)
                    del files[rel]
            continue
        text = path.read_text(encoding="utf-8")
        file_changed, mem_changed = _sha(text) != ent["file_sha"], cur_mem != ent["mem_sha"]
        if not file_changed and not mem_changed:
            rep["unchanged"] += 1
        elif file_changed and mem_changed:
            rep["conflicts"].append({"path": rel, "memory_ids": ids, "reason": "file and memory both changed since the last sync"})
        elif file_changed:
            if do_in:
                _file_to_memory(mem, rel, ent, text, kw, rep, dry_run)
        elif do_out:
            if len(ids) != 1:
                rep["memory_changed_not_pushed"].append(rel)
            else:
                rep["updated_from_memory"].append(rel)
                if not dry_run:
                    rec = mem.get(ids[0], **kw)
                    new_text = _render_export(rec) if ent["kind"] == "export" else rec.original_content
                    _write(path, new_text)
                    ent["file_sha"], ent["mem_sha"] = _sha(new_text), cur_mem

    # 2. new notes become memories
    if do_in:
        for path in sorted(root.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            parts = path.relative_to(root).parts
            if rel in files or parts[0] == EXPORT_DIR or any(p.startswith(".") for p in parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                rep["skipped"].append({"path": rel, "reason": "not valid UTF-8"})
                continue
            if not text.strip():
                rep["skipped"].append({"path": rel, "reason": "empty"})
                continue
            rep["imported"].append(rel)
            if dry_run:
                continue
            res = mem.remember(text, source_type="document", origin=f"vault:{rel}", **kw)
            files[rel] = {
                "kind": "import", "memory_ids": res.memory_ids, "shared": bool(res.duplicate_of),
                "file_sha": _sha(text), "mem_sha": mem_sha(res.memory_ids),
            }

    # 3. memories that have no file yet
    if do_out:
        tracked = {i for e in files.values() for i in e["memory_ids"]}
        offset = 0
        while True:
            batch = mem.list_memories(**kw, limit=500, offset=offset, include_derived=False)
            if not batch:
                break
            offset += len(batch)
            for rec in batch:
                if rec.id in tracked:
                    continue
                rel = f"{EXPORT_DIR}/{rec.id}.md"
                rep["exported"].append(rel)
                if dry_run:
                    continue
                text = _render_export(rec)
                _write(root / rel, text)
                files[rel] = {"kind": "export", "memory_ids": [rec.id], "shared": False, "file_sha": _sha(text), "mem_sha": mem_sha([rec.id])}

    if not dry_run:
        _save_state(root, state)
    return rep


def _file_to_memory(mem: MemoryOS, rel: str, ent: dict, text: str, kw: dict, rep: dict, dry_run: bool) -> None:
    """Apply an edited file to its memory: a new version when possible, otherwise a re-ingest."""
    content = text if ent["kind"] == "import" else split_front_matter(text)[1].strip("\n")
    if not content.strip():
        rep["skipped"].append({"path": rel, "reason": "edited to empty; delete the memory explicitly if intended"})
        return
    ids: list[str] = ent["memory_ids"]
    single = len(ids) == 1 and not ent.get("shared")
    one_chunk = len(chunk_text(content, mem.settings.chunk_chars, mem.settings.chunk_overlap)) <= 1
    in_place = single and (one_chunk or ent["kind"] == "export")
    rep["updated_from_file"].append({"path": rel, "history_kept": in_place})
    if dry_run:
        return
    if in_place:
        mem.correct(ids[0], content, reason="vault sync: note edited", **kw)
        new_ids, shared = ids, False
    else:
        res = mem.remember(content, source_type="document", origin=f"vault:{rel}", **kw)
        if not ent.get("shared"):
            for i in ids:
                if i not in res.memory_ids:
                    mem.forget(i, **kw)
        new_ids, shared = res.memory_ids, bool(res.duplicate_of) and res.duplicate_of not in ids
    parts = []
    for i in new_ids:
        r = mem.get(i, **kw)
        parts.append(f"{r.id}:{r.version}:{r.original_content}")
    ent.update(memory_ids=new_ids, shared=shared, file_sha=_sha(text), mem_sha=_sha("\n".join(parts)))
