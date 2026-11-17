"""HTTP client for a running MemoraOS REST API. (The in-process API is ``memoraos.MemoryOS``.)"""

from __future__ import annotations

from typing import Any

import httpx


class MemoraError(RuntimeError):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


class MemoraClient:
    """Every call is scoped to ``user_id``; the API key binds the tenant and role server-side."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", api_key: str | None = None, *, user_id: str, timeout: float = 30.0, client: httpx.Client | None = None):
        self.user_id = user_id
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers)

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        r = self._http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text
            raise MemoraError(r.status_code, detail)
        return r.json()

    def remember(self, text: str, **kw: Any) -> dict:
        return self._req("POST", "/v1/memories", json={"text": text, "user_id": self.user_id, **kw})

    def remember_json(self, record: dict | list, **kw: Any) -> list[dict]:
        """Store structured records ``{subject, predicate, object, valid_from?, valid_until?}`` as dated facts."""
        return self._req("POST", "/v1/memories/json", json={"record": record, "user_id": self.user_id, **kw})

    def recall(self, query: str, **kw: Any) -> dict:
        return self._req("POST", "/v1/recall", json={"query": query, "user_id": self.user_id, **kw})

    def correct(self, memory_id: str, new_content: str, reason: str | None = None) -> dict:
        return self._req("PATCH", f"/v1/memories/{memory_id}", json={"user_id": self.user_id, "new_content": new_content, "reason": reason})

    def forget(self, memory_id: str) -> dict:
        return self._req("DELETE", f"/v1/memories/{memory_id}", params={"user_id": self.user_id})

    def history(self, subject: str, predicate: str) -> dict:
        return self._req("GET", "/v1/history", params={"subject": subject, "predicate": predicate, "user_id": self.user_id})

    def explain(self, recall_id: str) -> dict:
        return self._req("GET", f"/v1/explain/{recall_id}", params={"user_id": self.user_id})

    def consolidate(self, mode: str = "manual") -> dict:
        return self._req("POST", "/v1/consolidate", json={"user_id": self.user_id, "mode": mode})

    def feedback(self, recall_id: str, correct: bool | None = None, relevance: float | None = None) -> dict:
        return self._req("POST", "/v1/feedback", json={"recall_id": recall_id, "correct": correct, "relevance": relevance})

    def export(self) -> dict:
        return self._req("GET", "/v1/export", params={"user_id": self.user_id})

    def stats(self) -> dict:
        return self._req("GET", "/v1/stats")
