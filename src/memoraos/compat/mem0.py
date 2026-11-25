"""A Mem0-shaped facade over MemoraOS, for trying MemoraOS in code written against Mem0's ``Memory`` class.

It mirrors the method names, arguments and return shapes of ``mem0.Memory`` (``add``, ``search``, ``get_all``, ``get``,
``update``, ``delete``, ``delete_all``, ``history``) as read from the ``mem0ai`` 2.2.1 source. It is **not** Mem0:

* ``infer`` is ignored. Text is stored as given (MemoraOS extracts facts with its own rules); nothing is rewritten
  by an LLM.
* ``search`` returns the evidence MemoraOS cites, and an empty list when it has no supporting evidence.
* Mem0's ``user_id`` / ``agent_id`` / ``run_id`` all map to one MemoraOS owner id (the first one given); the other
  two are kept as metadata only.
* ``get`` / ``update`` / ``delete`` look the owner up from the memory id, because Mem0's signatures do not carry
  one. Use it on a local, single-tenant store; the shim does no access control.
"""

from __future__ import annotations

from typing import Any

from ..engine import MemoryOS, NotFoundError


class Memory:
    def __init__(self, engine: MemoryOS | None = None, *, path: str | None = None, tenant_id: str = "default"):
        self.engine = engine or MemoryOS.local(path)
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _owner(user_id: str | None, agent_id: str | None, run_id: str | None, filters: dict | None = None) -> str:
        f = filters or {}
        user_id, agent_id, run_id = user_id or f.get("user_id"), agent_id or f.get("agent_id"), run_id or f.get("run_id")
        if user_id:
            return str(user_id)
        if agent_id:
            return f"agent:{agent_id}"
        if run_id:
            return f"run:{run_id}"
        raise ValueError("provide at least one of user_id, agent_id or run_id")

    def _owner_of(self, memory_id: str) -> str:
        row = self.engine.db.one("SELECT user_id FROM memories WHERE id=? AND tenant_id=?", (memory_id, self.tenant_id))
        if not row:
            raise ValueError(f"Memory with id {memory_id} not found")
        return row["user_id"]

    def _item(self, rec: Any) -> dict:
        return {
            "id": rec.id, "memory": rec.original_content, "hash": _md5(rec.original_content),
            "created_at": rec.created_at, "updated_at": rec.updated_at, "user_id": rec.user_id, "metadata": rec.metadata or None,
        }

    # ------------------------------------------------------------------ Mem0 API
    def add(
        self, messages: str | dict | list[dict], *, user_id: str | None = None, agent_id: str | None = None,
        run_id: str | None = None, metadata: dict | None = None, infer: bool = True, **_: Any,
    ) -> dict:
        owner = self._owner(user_id, agent_id, run_id)
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        elif isinstance(messages, dict):
            messages = [messages]
        results = []
        for m in messages:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            role = m.get("role", "user")
            md = {**(metadata or {}), "role": role, **({"agent_id": agent_id} if agent_id else {}), **({"run_id": run_id} if run_id else {})}
            res = self.engine.remember(
                content, user_id=owner, tenant_id=self.tenant_id, source_type="conversation" if role == "user" else "inferred",
                metadata=md, extract=role == "user",
            )
            for mid in res.memory_ids:
                rec = self.engine.get(mid, user_id=owner, tenant_id=self.tenant_id)
                results.append({"id": mid, "memory": rec.original_content, "event": "NONE" if res.duplicate_of == mid else "ADD", "role": role})
        return {"results": results}

    def search(
        self, query: str, *, user_id: str | None = None, agent_id: str | None = None, run_id: str | None = None,
        filters: dict | None = None, top_k: int | None = None, limit: int | None = None, threshold: float | None = None, **_: Any,
    ) -> dict:
        owner = self._owner(user_id, agent_id, run_id, filters)
        res = self.engine.recall(query, user_id=owner, tenant_id=self.tenant_id, top_k=top_k or limit or 5)
        items = []
        if res.supported:
            for ev in res.evidence:
                if threshold is not None and ev.score < threshold:
                    continue
                items.append({
                    "id": ev.memory_id, "memory": ev.excerpt, "score": ev.score, "user_id": owner,
                    "metadata": {"verification": ev.verification, "source_type": ev.source_type, "span_start": ev.span_start, "span_end": ev.span_end, "quote_sha256": ev.quote_sha256},
                })
        # "memoraos" is an extension; Mem0 has no equivalent
        return {"results": items, "memoraos": {"status": res.status, "answer": res.answer, "recall_id": res.recall_id}}

    def get_all(
        self, *, user_id: str | None = None, agent_id: str | None = None, run_id: str | None = None,
        filters: dict | None = None, top_k: int | None = None, limit: int | None = None, **_: Any,
    ) -> dict:
        owner = self._owner(user_id, agent_id, run_id, filters)
        recs = self.engine.list_memories(user_id=owner, tenant_id=self.tenant_id, limit=top_k or limit or 100, include_derived=False)
        return {"results": [self._item(r) for r in recs]}

    def get(self, memory_id: str) -> dict:
        owner = self._owner_of(memory_id)
        return self._item(self.engine.get(memory_id, user_id=owner, tenant_id=self.tenant_id))

    def update(self, memory_id: str, text: str | None = None, metadata: dict | None = None, data: str | None = None, **_: Any) -> dict:
        new = text or data
        if not new:
            raise ValueError("MemoraOS can only update a memory's text; pass text")
        self.engine.correct(memory_id, new, user_id=self._owner_of(memory_id), tenant_id=self.tenant_id, reason="mem0-compat update")
        return {"message": "Memory updated successfully!"}

    def delete(self, memory_id: str) -> dict:
        self.engine.forget(memory_id, user_id=self._owner_of(memory_id), tenant_id=self.tenant_id)
        return {"message": "Memory deleted successfully!"}

    def delete_all(self, user_id: str | None = None, agent_id: str | None = None, run_id: str | None = None) -> dict:
        self.engine.forget(everything=True, user_id=self._owner(user_id, agent_id, run_id), tenant_id=self.tenant_id)
        return {"message": "Memories deleted successfully!"}

    def history(self, memory_id: str) -> list[dict]:
        try:
            h = self.engine.history(memory_id, user_id=self._owner_of(memory_id), tenant_id=self.tenant_id)
        except NotFoundError as exc:
            raise ValueError(f"Memory with id {memory_id} not found") from exc
        out, prev = [], None
        for v in h["versions"]:
            out.append({
                "id": f"{memory_id}:{v['version']}", "memory_id": memory_id, "old_memory": prev, "new_memory": v["original_content"],
                "event": "ADD" if prev is None else "UPDATE", "created_at": v["changed_at"], "updated_at": None,
                "is_deleted": False, "actor_id": v["actor"], "role": None,
            })
            prev = v["original_content"]
        return out


def _md5(text: str) -> str:
    import hashlib

    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()  # noqa: S324 - same non-security hash Mem0 reports
