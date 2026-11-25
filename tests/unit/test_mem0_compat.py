from __future__ import annotations

import pytest

from memoraos import MemoryOS
from memoraos.compat.mem0 import Memory

U = "alice"


@pytest.fixture()
def m():
    mm = Memory(MemoryOS.in_memory())
    yield mm
    mm.engine.close()


def test_mem0_shaped_round_trip(m):
    added = m.add("My favorite color is blue.", user_id=U, metadata={"topic": "prefs"})
    (item,) = added["results"]
    assert set(item) >= {"id", "memory", "event"} and item["event"] == "ADD"

    found = m.search("What is my favorite color?", user_id=U)
    assert found["results"] and found["results"][0]["id"] == item["id"]
    assert set(found["results"][0]) >= {"id", "memory", "score", "metadata"}

    allm = m.get_all(user_id=U)["results"]
    assert [x["id"] for x in allm] == [item["id"]] and set(allm[0]) >= {"id", "memory", "hash", "created_at", "updated_at", "user_id", "metadata"}
    assert allm[0]["metadata"]["topic"] == "prefs"
    assert m.get(item["id"])["memory"] == "My favorite color is blue."

    assert m.update(item["id"], text="My favorite color is green.") == {"message": "Memory updated successfully!"}
    hist = m.history(item["id"])
    assert [h["event"] for h in hist] == ["ADD", "UPDATE"] and hist[1]["old_memory"] == "My favorite color is blue."
    assert set(hist[0]) >= {"id", "memory_id", "old_memory", "new_memory", "event", "created_at", "updated_at", "is_deleted", "actor_id", "role"}

    assert m.delete(item["id"]) == {"message": "Memory deleted successfully!"}
    assert m.get_all(user_id=U)["results"] == []


def test_message_lists_filters_and_abstention(m):
    m.add([{"role": "user", "content": "I live in Pune."}, {"role": "assistant", "content": "Noted, Pune."}], user_id=U)
    assert len(m.get_all(filters={"user_id": U})["results"]) == 2
    assert m.search("What is the airspeed of a swallow?", filters={"user_id": U})["results"] == []
    assert m.add("I live in Pune.", user_id=U)["results"][0]["event"] == "NONE"  # duplicate
    other = m.search("Where do I live?", user_id="bob")
    assert other["results"] == []  # users are separate
    assert m.delete_all(user_id=U) == {"message": "Memories deleted successfully!"}
    assert m.get_all(user_id=U)["results"] == []


def test_validation(m):
    with pytest.raises(ValueError):
        m.search("anything")
    with pytest.raises(ValueError):
        m.get("mem_missing")
    with pytest.raises(ValueError):
        m.update("mem_missing", text="x")
    mid = m.add("Plain note.", agent_id="bot")["results"][0]["id"]
    assert m.get(mid)["user_id"] == "agent:bot"
    with pytest.raises(ValueError):
        m.update(mid, metadata={"a": 1})
