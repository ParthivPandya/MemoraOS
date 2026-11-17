"""HTTP-backed providers (Ollama, OpenAI-compatible) with timeouts, retries and fallback.

None of these are used unless explicitly configured; basic MemoraOS never makes network calls.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import numpy as np

from .base import (
    ChatProvider,
    ChatResponse,
    EmbeddingProvider,
    ProviderError,
    ProviderUnavailable,
    Usage,
)

UsageSink = Callable[[Usage], None]


class _HttpClientMixin:
    name: str

    def _init_http(
        self,
        base_url: str,
        *,
        api_key: str | None,
        timeout: float,
        max_retries: int,
        client: httpx.Client | None,
        sleep: Callable[[float], None],
        usage_sink: UsageSink | None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._usage_sink = usage_sink
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=timeout, headers=headers)

    def _post(self, path: str, payload: dict) -> dict:
        """POST with exponential backoff on 429/5xx/timeouts; honours Retry-After."""
        url = f"{self.base_url}{path}"
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.post(url, json=payload, timeout=self.timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                self._sleep(min(2**attempt * 0.5, 8.0))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = ProviderError(f"{self.name}: HTTP {resp.status_code}")
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else 2**attempt * 0.5
                self._sleep(min(delay, 30.0))
                continue
            if resp.status_code in (401, 403):
                raise ProviderError(f"{self.name}: authentication failed (HTTP {resp.status_code})")
            if resp.status_code == 404:
                raise ProviderUnavailable(f"{self.name}: endpoint or model not found at {url}")
            if resp.status_code >= 400:
                raise ProviderError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                return resp.json()
            except ValueError as exc:
                raise ProviderError(f"{self.name}: invalid JSON response") from exc
        raise ProviderUnavailable(f"{self.name}: failed after {self.max_retries + 1} attempts: {last}")

    def _record(self, usage: Usage) -> None:
        if self._usage_sink:
            self._usage_sink(usage)


def _normalize(m: np.ndarray) -> np.ndarray:
    m = m.astype(np.float32, copy=False)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class OllamaEmbedder(_HttpClientMixin):
    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        *,
        dim: int = 768,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        usage_sink: UsageSink | None = None,
    ):
        self.name = f"ollama:{model}"
        self.model = model
        self.dim = dim
        self._init_http(base_url, api_key=None, timeout=timeout, max_retries=max_retries, client=client, sleep=sleep, usage_sink=usage_sink)

    def is_available(self) -> bool:
        try:
            r = self._client.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            return r.status_code == 200 and any(m.get("name", "").startswith(self.model) for m in r.json().get("models", []))
        except (httpx.HTTPError, ValueError):
            return False

    def embed(self, texts: list[str]) -> np.ndarray:
        t0 = time.perf_counter()
        data = self._post("/api/embed", {"model": self.model, "input": texts})
        vecs = data.get("embeddings")
        if not vecs or len(vecs) != len(texts):
            raise ProviderError(f"{self.name}: malformed embedding response")
        arr = np.asarray(vecs, dtype=np.float32)
        self.dim = arr.shape[1]
        self._record(Usage("ollama", self.model, "embedding", tokens_in=sum(len(t) // 4 for t in texts), latency_ms=(time.perf_counter() - t0) * 1000))
        return _normalize(arr)


class OpenAICompatEmbedder(_HttpClientMixin):
    """Any OpenAI-compatible ``/embeddings`` endpoint (OpenRouter, vLLM, LM Studio, ...)."""

    def __init__(
        self,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        *,
        api_key: str | None = None,
        dim: int = 1536,
        cost_per_1k_tokens: float = 0.0,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        usage_sink: UsageSink | None = None,
    ):
        self.name = f"openai-compat:{model}"
        self.model = model
        self.dim = dim
        self.cost_per_1k = cost_per_1k_tokens
        self._init_http(base_url, api_key=api_key, timeout=timeout, max_retries=max_retries, client=client, sleep=sleep, usage_sink=usage_sink)

    def embed(self, texts: list[str]) -> np.ndarray:
        t0 = time.perf_counter()
        data = self._post("/embeddings", {"model": self.model, "input": texts})
        try:
            rows = sorted(data["data"], key=lambda r: r["index"])
            arr = np.asarray([r["embedding"] for r in rows], dtype=np.float32)
        except (KeyError, TypeError) as exc:
            raise ProviderError(f"{self.name}: malformed embedding response") from exc
        if arr.shape[0] != len(texts):
            raise ProviderError(f"{self.name}: expected {len(texts)} embeddings, got {arr.shape[0]}")
        self.dim = arr.shape[1]
        tokens = int(data.get("usage", {}).get("total_tokens", sum(len(t) // 4 for t in texts)))
        self._record(Usage("openai-compat", self.model, "embedding", tokens_in=tokens, cost=tokens / 1000 * self.cost_per_1k, latency_ms=(time.perf_counter() - t0) * 1000))
        return _normalize(arr)


class OpenAICompatChat(_HttpClientMixin):
    """OpenAI-compatible ``/chat/completions`` (works with Ollama's /v1, OpenRouter, vLLM, ...)."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        *,
        api_key: str | None = None,
        cost_per_1k_in: float = 0.0,
        cost_per_1k_out: float = 0.0,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        usage_sink: UsageSink | None = None,
    ):
        self.name = f"chat:{model}"
        self.model = model
        self.cost_in = cost_per_1k_in
        self.cost_out = cost_per_1k_out
        self._init_http(base_url, api_key=api_key, timeout=timeout, max_retries=max_retries, client=client, sleep=sleep, usage_sink=usage_sink)

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 512) -> ChatResponse:
        t0 = time.perf_counter()
        data = self._post("/chat/completions", {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0})
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.name}: malformed chat response") from exc
        u = data.get("usage", {})
        tin, tout = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
        usage = Usage("openai-compat", self.model, "chat", tin, tout, tin / 1000 * self.cost_in + tout / 1000 * self.cost_out, (time.perf_counter() - t0) * 1000)
        self._record(usage)
        return ChatResponse(text=text, usage=usage)


class FallbackEmbedder:
    """Try providers in order; the first that succeeds wins. Dimensions must match."""

    def __init__(self, providers: list[EmbeddingProvider]):
        if not providers:
            raise ValueError("at least one provider required")
        self.providers = providers
        self.name = "fallback(" + ",".join(p.name for p in providers) + ")"
        self.dim = providers[0].dim
        self.last_used: str | None = None
        self._locked_dim: int | None = None

    def embed(self, texts: list[str]) -> np.ndarray:
        """Vectors from different providers are not comparable, so after the first success every
        later provider must return the same dimension; mismatching providers are skipped."""
        errors = []
        for p in self.providers:
            try:
                out = p.embed(texts)
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            if self._locked_dim is not None and out.shape[1] != self._locked_dim:
                errors.append(f"{p.name}: dimension {out.shape[1]} != {self._locked_dim}")
                continue
            self._locked_dim = out.shape[1]
            self.last_used = p.name
            self.dim = out.shape[1]
            return out
        raise ProviderUnavailable("all embedding providers failed: " + "; ".join(errors))


class FallbackChat:
    def __init__(self, providers: list[ChatProvider]):
        if not providers:
            raise ValueError("at least one provider required")
        self.providers = providers
        self.name = "fallback(" + ",".join(p.name for p in providers) + ")"

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 512) -> ChatResponse:
        errors = []
        for p in self.providers:
            try:
                return p.complete(messages, max_tokens=max_tokens)
            except ProviderError as exc:
                errors.append(str(exc))
        raise ProviderUnavailable("all chat providers failed: " + "; ".join(errors))
