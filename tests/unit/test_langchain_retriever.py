from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from memoraos import MemoryOS  # noqa: E402
from memoraos.integrations.langchain import MemoraOSRetriever  # noqa: E402

U = "lc_user"


@pytest.fixture()
def mem():
    m = MemoryOS.in_memory()
    m.remember("The customer plan is Professional.", user_id=U, effective_at="2026-01-01")
    m.remember("The customer plan is Enterprise.", user_id=U, effective_at="2026-06-01")
    yield m
    m.close()


def test_retriever_returns_cited_documents(mem):
    docs = MemoraOSRetriever(memory=mem, user_id=U, top_k=3).invoke("What is the customer plan?")
    assert docs and "Enterprise" in docs[0].page_content
    md = docs[0].metadata
    assert md["memory_id"] and md["quote_sha256"] and md["span_start"] is not None
    verdict = mem.verify_citations([{"memory_id": md["memory_id"], "excerpt": docs[0].page_content, "span_start": md["span_start"], "span_end": md["span_end"], "quote_sha256": md["quote_sha256"]}], user_id=U)
    assert verdict["results"][0]["status"] == "verified"


def test_retriever_abstains_and_respects_as_of(mem):
    r = MemoraOSRetriever(memory=mem, user_id=U)
    assert r.invoke("What is the airspeed velocity of an unladen swallow?") == []
    # as_of is "what had been recorded by then": nothing had been, so the retriever abstains
    assert MemoraOSRetriever(memory=mem, user_id=U, as_of="2000-01-01").invoke("What is the customer plan?") == []
