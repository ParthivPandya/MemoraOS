"""The Python client talks to the real FastAPI app through an in-process ASGI transport."""

import httpx
import pytest
from fastapi.testclient import TestClient

from memoraos.api import ApiKeyStore
from memoraos.api.app import create_app
from memoraos.client import MemoraClient, MemoraError


@pytest.fixture
def sdk(mem):
    app = create_app(mem, ApiKeyStore.from_plain({"k": {"tenant": "t", "role": "admin"}}))
    http = TestClient(app, headers={"Authorization": "Bearer k"})
    return MemoraClient(user_id="u1", client=http)  # type: ignore[arg-type]


def test_sdk_round_trip(sdk):
    mid = sdk.remember("Parth's salary is ₹32 LPA.")["memory_ids"][0]
    res = sdk.recall("What is Parth's salary?")
    assert res["answer"] == "₹32 LPA" and sdk.explain(res["recall_id"])["strategy"] == "exact"
    assert sdk.history("Parth", "salary")["timeline"][0]["value"] == "₹32 LPA"
    assert sdk.correct(mid, "Parth's salary is ₹33 LPA.", "raise")["version"] == 2
    assert sdk.export()["memories"] and sdk.stats()["memories"] == 1
    assert sdk.forget(mid) == {"deleted": 1}


def test_sdk_raises_with_status(sdk):
    with pytest.raises(MemoraError) as e:
        sdk.recall("")
    assert e.value.status == 422
    assert isinstance(httpx.Client, type)
