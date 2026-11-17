import json

import pytest
from fastapi.testclient import TestClient

from memoraos.api import ApiKeyStore
from memoraos.api.app import create_app

ADMIN, WRITER, READER, OTHER = "k-admin-secret", "k-writer-secret", "k-reader-secret", "k-other-tenant"


@pytest.fixture
def client(mem):
    keys = ApiKeyStore.from_plain({
        ADMIN: {"tenant": "acme", "role": "admin"},
        WRITER: {"tenant": "acme", "role": "write"},
        READER: {"tenant": "acme", "role": "read"},
        OTHER: {"tenant": "globex", "role": "admin"},
    })
    return TestClient(create_app(mem, keys))


def h(key):
    return {"Authorization": f"Bearer {key}"}


def test_refuses_to_start_without_keys(mem):
    with pytest.raises(RuntimeError, match="No API keys"):
        create_app(mem, ApiKeyStore())
    assert TestClient(create_app(mem, ApiKeyStore(), insecure_no_auth=True)).get("/v1/stats").status_code == 200


def test_authentication_and_roles(client):
    assert client.get("/v1/health").json()["status"] == "ok"
    assert client.get("/v1/stats").status_code == 401
    assert client.get("/v1/stats", headers=h("wrong")).status_code == 401
    body = {"text": "Parth's salary is ₹32 LPA.", "user_id": "u1"}
    assert client.post("/v1/memories", json=body, headers=h(READER)).status_code == 403
    assert client.post("/v1/memories", json=body, headers=h(WRITER)).status_code == 201
    assert client.delete("/v1/users/u1", headers=h(WRITER)).status_code == 403
    assert client.delete("/v1/users/u1", headers=h(ADMIN)).status_code == 200


def test_full_lifecycle_over_http(client):
    r = client.post("/v1/memories", json={"text": "Parth's salary is ₹28 LPA in 2024.", "user_id": "u1"}, headers=h(WRITER)).json()
    mid = r["memory_ids"][0]
    client.post("/v1/memories", json={"text": "Parth's salary is ₹32 LPA in 2026.", "user_id": "u1"}, headers=h(WRITER))
    rec = client.post("/v1/recall", json={"query": "What is Parth's current salary?", "user_id": "u1"}, headers=h(READER)).json()
    assert rec["answer"] == "₹32 LPA" and rec["strategy"] == "exact" and rec["evidence"][0]["memory_id"]
    ex = client.get(f"/v1/explain/{rec['recall_id']}", params={"user_id": "u1"}, headers=h(READER)).json()
    assert ex["strategy"] == "exact"
    assert client.post("/v1/feedback", json={"recall_id": rec["recall_id"], "correct": True}, headers=h(WRITER)).status_code == 200
    assert client.get("/v1/strategies", headers=h(READER)).json()[0]["n"] == 1
    fixed = client.patch(f"/v1/memories/{mid}", json={"user_id": "u1", "new_content": "Parth's salary is ₹29 LPA in 2024.", "reason": "typo"}, headers=h(WRITER)).json()
    assert fixed["version"] == 2
    hist = client.get(f"/v1/memories/{mid}/history", params={"user_id": "u1"}, headers=h(READER)).json()
    assert len(hist["versions"]) == 2
    assert client.get("/v1/facts", params={"user_id": "u1"}, headers=h(READER)).json()
    assert client.get("/v1/graph", params={"user_id": "u1"}, headers=h(READER)).status_code == 200
    assert client.get("/v1/contradictions", params={"user_id": "u1"}, headers=h(READER)).status_code == 200
    assert client.get("/v1/export", params={"user_id": "u1"}, headers=h(READER)).json()["memories"]
    assert client.delete(f"/v1/memories/{mid}", params={"user_id": "u1"}, headers=h(WRITER)).json() == {"deleted": 1}
    assert client.get(f"/v1/memories/{mid}", params={"user_id": "u1"}, headers=h(READER)).status_code == 404


def test_tenant_isolation_through_api_keys(client):
    client.post("/v1/memories", json={"text": "Parth's salary is ₹32 LPA.", "user_id": "u1"}, headers=h(WRITER))
    leak = client.post("/v1/recall", json={"query": "What is Parth's salary?", "user_id": "u1"}, headers=h(OTHER)).json()
    assert leak["status"] == "insufficient_evidence" and not leak["evidence"]
    assert client.get("/v1/memories", params={"user_id": "u1"}, headers=h(OTHER)).json() == []
    assert client.get("/v1/stats", headers=h(OTHER)).json()["memories"] == 0
    rec = client.post("/v1/recall", json={"query": "What is Parth's salary?", "user_id": "u1"}, headers=h(READER)).json()
    assert client.get(f"/v1/explain/{rec['recall_id']}", params={"user_id": "u1"}, headers=h(OTHER)).status_code == 404
    assert client.post("/v1/feedback", json={"recall_id": rec["recall_id"], "correct": False}, headers=h(OTHER)).status_code == 404


def test_key_can_be_restricted_to_users(mem):
    keys = ApiKeyStore.from_plain({"k": {"tenant": "t", "role": "write", "users": ["only_me"]}})
    c = TestClient(create_app(mem, keys))
    assert c.post("/v1/memories", json={"text": "I live in Pune.", "user_id": "someone_else"}, headers=h("k")).status_code == 403
    assert c.post("/v1/memories", json={"text": "I live in Pune.", "user_id": "only_me"}, headers=h("k")).status_code == 201


def test_input_validation_and_errors(client):
    assert client.post("/v1/memories", json={"text": "", "user_id": "u"}, headers=h(WRITER)).status_code == 422
    assert client.post("/v1/memories", json={"text": "x", "user_id": "u", "source_type": "consolidation"}, headers=h(WRITER)).status_code == 422
    assert client.post("/v1/recall", json={"query": "x", "user_id": "u", "strategy": "drop table"}, headers=h(READER)).status_code == 422
    assert client.post("/v1/recall", json={"query": "x" * 5000, "user_id": "u"}, headers=h(READER)).status_code == 422
    assert client.get("/v1/memories/nope", params={"user_id": "u"}, headers=h(READER)).status_code == 404


def test_audit_log_records_actor_fingerprint_not_key(client, mem):
    client.post("/v1/memories", json={"text": "I live in Pune.", "user_id": "u"}, headers=h(WRITER))
    rows = mem.db.query("SELECT actor, action FROM audit_log")
    assert rows and rows[0]["action"] == "remember" and WRITER not in str(rows[0]["actor"]) and len(rows[0]["actor"]) == 8


def test_key_store_hashes_keys_on_disk(tmp_path):
    p = tmp_path / "keys.json"
    key = ApiKeyStore.create(p, "acme", "admin")
    text = p.read_text()
    assert key not in text and json.loads(text)
    store = ApiKeyStore.load(p)
    assert store.authenticate(key).tenant_id == "acme" and store.authenticate("nope") is None
    with pytest.raises(ValueError):
        ApiKeyStore.create(p, "t", "root")


def test_benchmarks_endpoint_serves_report_files(mem, tmp_path):
    (tmp_path / "benchmark_results.json").write_text(json.dumps({"benchmark": "x"}))
    c = TestClient(create_app(mem, ApiKeyStore.from_plain({"k": {"tenant": "t", "role": "read"}}), reports_dir=tmp_path))
    assert c.get("/v1/benchmarks", headers=h("k")).json() == [{"benchmark": "x"}]
