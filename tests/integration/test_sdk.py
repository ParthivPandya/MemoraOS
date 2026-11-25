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


def test_sdk_covers_verification_outcomes_links_and_replay(sdk):
    cause = sdk.remember("The release was blocked by a failing test.", verification="hypothesis")["memory_ids"][0]
    effect = sdk.remember("Fixing the test unblocked the release.")["memory_ids"][0]
    assert sdk.verify(cause, "verified") == {"memory_id": cause, "verification": "verified"}
    sdk.link(effect, cause, "solves")
    assert {n["memory_id"] for n in sdk.lineage(cause, direction="up")["nodes"]} == {cause, effect}
    res = sdk.recall("What blocked the release?")
    checked = sdk.verify_citations(res["evidence"])
    assert checked["results"] and all(c["status"] == "verified" for c in checked["results"] if c["memory_id"] in (cause, effect))
    assert sdk.replay(res["recall_id"], leave_one_out=True)["runs"]
    sdk.remember_outcome("upgrade the requests library to 3.0", "failed", reason="breaks the retry adapter")
    warnings = sdk.outcome_warnings("upgrade requests library")
    assert len(warnings) == 1 and warnings[0]["reason"] == "breaks the retry adapter"
