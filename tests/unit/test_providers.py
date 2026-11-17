import httpx
import numpy as np
import pytest

from memoraos.providers import (
    FallbackChat,
    FallbackEmbedder,
    HashingEmbedder,
    LexicalReranker,
    OllamaEmbedder,
    OpenAICompatChat,
    OpenAICompatEmbedder,
    ProviderError,
    ProviderUnavailable,
    Usage,
)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_hashing_embedder_is_deterministic_normalised_and_lexically_sensible():
    e = HashingEmbedder(256)
    a, b = e.embed(["Priya lives in Pune"]), e.embed(["Priya lives in Pune"])
    assert np.array_equal(a, b) and abs(np.linalg.norm(a[0]) - 1) < 1e-5
    q, near, far = e.embed(["Where does Priya live?", "Priya lives in Pune", "Quarterly vendor budget review"])
    assert q @ near > q @ far + 0.2


def test_reranker():
    assert LexicalReranker().rerank("azure cost", ["azure cost report", "unrelated"]) == [1.0, 0.0]


def test_openai_compat_embedder_parses_and_tracks_usage():
    seen = []

    def handler(req):
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 3, 4]}, {"index": 0, "embedding": [1, 0, 0]}], "usage": {"total_tokens": 10}})

    emb = OpenAICompatEmbedder("m", "http://x/v1", api_key="k", cost_per_1k_tokens=0.5, client=client(handler), usage_sink=seen.append)
    out = emb.embed(["a", "b"])
    assert out.shape == (2, 3) and np.allclose(out[1], [0, 0.6, 0.8]) and np.allclose(out[0], [1, 0, 0])
    assert seen[0].tokens_in == 10 and seen[0].cost == pytest.approx(0.005)


def test_retries_with_backoff_and_retry_after():
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    chat = OpenAICompatChat("m", "http://x/v1", client=client(handler), sleep=sleeps.append, cost_per_1k_in=1, cost_per_1k_out=2)
    r = chat.complete([{"role": "user", "content": "q"}])
    assert r.text == "hi" and len(calls) == 3 and sleeps[0] == 2.0 and r.usage.cost == pytest.approx(0.005)


def test_gives_up_after_retries_and_reports_unavailable():
    chat = OpenAICompatChat("m", "http://x/v1", client=client(lambda r: httpx.Response(500)), sleep=lambda s: None, max_retries=1)
    with pytest.raises(ProviderUnavailable):
        chat.complete([{"role": "user", "content": "q"}])


def test_timeouts_are_retried_then_raised():
    def boom(req):
        raise httpx.ConnectTimeout("slow")

    emb = OllamaEmbedder("m", client=client(boom), sleep=lambda s: None, max_retries=1)
    with pytest.raises(ProviderUnavailable):
        emb.embed(["a"])


def test_auth_and_malformed_responses_fail_fast():
    with pytest.raises(ProviderError, match="authentication"):
        OpenAICompatChat("m", "http://x", client=client(lambda r: httpx.Response(401))).complete([])
    with pytest.raises(ProviderError, match="malformed"):
        OpenAICompatChat("m", "http://x", client=client(lambda r: httpx.Response(200, json={}))).complete([])
    with pytest.raises(ProviderError, match="malformed"):
        OllamaEmbedder("m", client=client(lambda r: httpx.Response(200, json={"embeddings": []}))).embed(["a"])


def test_model_availability_check():
    ok = OllamaEmbedder("nomic-embed-text", client=client(lambda r: httpx.Response(200, json={"models": [{"name": "nomic-embed-text:latest"}]})))
    assert ok.is_available()
    assert not OllamaEmbedder("other", client=client(lambda r: httpx.Response(200, json={"models": []}))).is_available()
    assert not OllamaEmbedder("x", client=client(lambda r: httpx.Response(500))).is_available()


def test_fallback_chain_uses_first_working_provider():
    bad = OpenAICompatEmbedder("m", "http://x", client=client(lambda r: httpx.Response(500)), sleep=lambda s: None, max_retries=0)
    chain = FallbackEmbedder([bad, HashingEmbedder(64)])
    out = chain.embed(["hello"])
    assert out.shape == (1, 64) and chain.last_used == "hashing-v1"
    with pytest.raises(ProviderUnavailable):
        FallbackEmbedder([bad]).embed(["x"])
    locked = FallbackEmbedder([HashingEmbedder(64), HashingEmbedder(32)])
    locked.embed(["a"])
    locked.providers = [HashingEmbedder(32)]  # a later provider with another dimension must be refused
    with pytest.raises(ProviderUnavailable, match="dimension"):
        locked.embed(["a"])

    class Good:
        name = "good"

        def complete(self, messages, *, max_tokens=512):
            from memoraos.providers.base import ChatResponse

            return ChatResponse("ok", Usage("g", "g", "chat"))

    class Bad:
        name = "bad"

        def complete(self, messages, *, max_tokens=512):
            raise ProviderUnavailable("down")

    assert FallbackChat([Bad(), Good()]).complete([]).text == "ok"


def test_engine_makes_no_network_calls_by_default(mem, monkeypatch):
    def forbid(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx.Client, "send", forbid)
    mem.remember("Alice leads Project Atlas.", user_id="u")
    assert mem.recall("Who leads Atlas?", user_id="u").answer == "Alice"


def test_engine_accepts_a_custom_embedder_and_reindexes_on_change(tmp_path):
    from memoraos import MemoryOS

    class Const:
        name = "const"
        dim = 8

        def embed(self, texts):
            v = np.zeros((len(texts), 8), np.float32)
            v[:, 0] = 1
            return v

    m = MemoryOS.local(tmp_path)
    m.remember("Zephyr runs on Rust.", user_id="u")
    m.close()
    m2 = MemoryOS.local(tmp_path, embedder=Const())
    assert m2.recall("zephyr", user_id="u", strategy="vector").evidence  # backfilled with the new model
    assert m2.db.one("SELECT COUNT(*) FROM embeddings WHERE model='const'")[0] == 1
    m2.close()
