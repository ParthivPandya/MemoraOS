from __future__ import annotations

import pytest

from memoraos import MemoryOS
from memoraos.vault import EXPORT_DIR, STATE_FILE, sync_vault

U = "user_001"


@pytest.fixture()
def mem():
    m = MemoryOS.in_memory()
    yield m
    m.close()


def _sync(mem, vault, **kw):
    return sync_vault(mem, vault, user_id=U, **kw)


def test_import_is_idempotent_and_keeps_original_text(mem, tmp_path):
    (tmp_path / "plan.md").write_text("# Plan\nThe launch is on 2026-03-01.\n", encoding="utf-8")
    first = _sync(mem, tmp_path)
    assert first["imported"] == ["plan.md"]
    second = _sync(mem, tmp_path)
    assert second["imported"] == [] and second["unchanged"] == 1
    mems = mem.list_memories(user_id=U)
    assert len(mems) == 1 and "launch is on 2026-03-01" in mems[0].original_content
    assert mems[0].source_type == "document"


def test_edited_note_creates_new_version_and_keeps_history(mem, tmp_path):
    note = tmp_path / "pricing.md"
    note.write_text("The customer plan is Professional.\n", encoding="utf-8")
    _sync(mem, tmp_path)
    note.write_text("The customer plan is Enterprise.\n", encoding="utf-8")
    rep = _sync(mem, tmp_path)
    assert rep["updated_from_file"] == [{"path": "pricing.md", "history_kept": True}]
    rec = mem.list_memories(user_id=U)[0]
    assert rec.version == 2 and "Enterprise" in rec.original_content
    assert len(mem.history(rec.id, user_id=U)["versions"]) == 2


def test_conflict_is_reported_and_nothing_is_overwritten(mem, tmp_path):
    note = tmp_path / "a.md"
    note.write_text("Alpha is blue.\n", encoding="utf-8")
    _sync(mem, tmp_path)
    mid = mem.list_memories(user_id=U)[0].id
    note.write_text("Alpha is red.\n", encoding="utf-8")
    mem.correct(mid, "Alpha is green.", user_id=U)
    rep = _sync(mem, tmp_path)
    assert [c["path"] for c in rep["conflicts"]] == ["a.md"]
    assert "red" in note.read_text(encoding="utf-8")
    assert "green" in mem.get(mid, user_id=U).original_content


def test_memory_edit_is_pushed_to_the_note(mem, tmp_path):
    note = tmp_path / "b.md"
    note.write_text("Beta is one.\n", encoding="utf-8")
    _sync(mem, tmp_path)
    mid = mem.list_memories(user_id=U)[0].id
    mem.correct(mid, "Beta is two.", user_id=U)
    rep = _sync(mem, tmp_path)
    assert rep["updated_from_memory"] == ["b.md"]
    assert note.read_text(encoding="utf-8").strip() == "Beta is two."
    assert _sync(mem, tmp_path)["unchanged"] == 1


def test_memories_are_exported_and_edits_round_trip(mem, tmp_path):
    mem.remember("The office is in Pune.", user_id=U)
    rep = _sync(mem, tmp_path)
    assert len(rep["exported"]) == 1
    exported = tmp_path / rep["exported"][0]
    assert exported.parent.name == EXPORT_DIR and "The office is in Pune." in exported.read_text(encoding="utf-8")
    assert _sync(mem, tmp_path)["exported"] == []  # exports are not re-imported or re-exported

    exported.write_text(exported.read_text(encoding="utf-8").replace("Pune", "Mumbai"), encoding="utf-8")
    rep = _sync(mem, tmp_path)
    assert rep["updated_from_file"][0]["history_kept"] is True
    assert "Mumbai" in mem.list_memories(user_id=U)[0].original_content
    assert len(mem.list_memories(user_id=U)) == 1


def test_deleted_note_needs_prune_and_dry_run_changes_nothing(mem, tmp_path):
    note = tmp_path / "c.md"
    note.write_text("Gamma exists.\n", encoding="utf-8")
    _sync(mem, tmp_path)
    note.unlink()
    rep = _sync(mem, tmp_path)
    assert rep["missing_files"] == ["c.md"] and len(mem.list_memories(user_id=U)) == 1
    dry = _sync(mem, tmp_path, prune=True, dry_run=True)
    assert dry["pruned"] == ["c.md"] and len(mem.list_memories(user_id=U)) == 1
    _sync(mem, tmp_path, prune=True)
    assert mem.list_memories(user_id=U) == []


def test_forgotten_memory_removes_its_export_only_with_prune(mem, tmp_path):
    mem.remember("Delta is private.", user_id=U)
    rel = _sync(mem, tmp_path)["exported"][0]
    mem.forget(everything=True, user_id=U)
    assert _sync(mem, tmp_path)["missing_memories"] == [rel] and (tmp_path / rel).exists()
    _sync(mem, tmp_path, prune=True)
    assert not (tmp_path / rel).exists()


def test_vault_is_bound_to_one_user_and_ignores_hidden_dirs(mem, tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "x.md").write_text("config", encoding="utf-8")
    _sync(mem, tmp_path)
    assert (tmp_path / STATE_FILE).is_file() and mem.list_memories(user_id=U) == []
    with pytest.raises(ValueError):
        sync_vault(mem, tmp_path, user_id="someone_else")


def test_multi_chunk_edit_reingests_without_duplicating(mem, tmp_path):
    note = tmp_path / "long.md"
    body = " ".join(f"Sentence number {i} talks about topic {i}." for i in range(80))
    note.write_text(body, encoding="utf-8")
    _sync(mem, tmp_path)
    n = len(mem.list_memories(user_id=U))
    assert n > 1
    note.write_text(body + " Final addition.", encoding="utf-8")
    rep = _sync(mem, tmp_path)
    assert rep["updated_from_file"] == [{"path": "long.md", "history_kept": False}]
    texts = " ".join(m.original_content for m in mem.list_memories(user_id=U))
    assert "Final addition" in texts
