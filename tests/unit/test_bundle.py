"""Portable bundles: round trip, tamper detection, signatures, idempotent import."""

from __future__ import annotations

import json

import pytest

from memoraos import MemoryOS
from memoraos.bundle import BundleError, export_bundle, import_bundle, read_bundle
from memoraos.cli import main

U = "user_001"


@pytest.fixture
def source(mem):
    a = mem.remember("The billing service uses MySQL.", user_id=U, effective_at="2026-01-01T00:00:00+00:00", verification="verified")
    b = mem.remember("The billing service uses Postgres.", user_id=U, effective_at="2026-06-01T00:00:00+00:00")
    c = mem.remember("We moved billing because MySQL replication lagged.", user_id=U, verification="hypothesis")
    mem.link(c.memory_ids[0], b.memory_ids[0], "causes", user_id=U)
    mem.remember("Another user's note.", user_id="other")
    return mem, a, b, c


def test_round_trip_keeps_text_time_verification_facts_and_links(source, tmp_path):
    mem, a, b, c = source
    rep = export_bundle(mem, tmp_path / "x.mem", user_id=U)
    assert rep["memories"] == 3 and rep["links"] == 1 and not rep["signed"]
    assert "Another user" not in (tmp_path / "x.mem").read_text(encoding="utf-8")
    dest = MemoryOS.in_memory()
    try:
        out = import_bundle(dest, tmp_path / "x.mem", user_id="newuser")
        assert out["imported"] == 3 and out["links"] == 1 and out["verified_downgraded"] == 1 and not out["signature_verified"]
        assert rep["facts"] > 0 and out["facts"] == rep["facts"]
        got = {m.original_content: m for m in dest.list_memories(user_id="newuser")}
        assert set(got) == {"The billing service uses MySQL.", "The billing service uses Postgres.", "We moved billing because MySQL replication lagged."}
        assert got["The billing service uses Postgres."].effective_at.startswith("2026-06-01")
        assert got["We moved billing because MySQL replication lagged."].verification == "hypothesis"
        assert got["The billing service uses MySQL."].verification == "unverified"
        res = dest.recall("Which database does billing use now?", user_id="newuser", use_cache=False)
        assert "Postgres" in (res.answer or "") or any("Postgres" in e.excerpt for e in res.evidence)
        cause = got["We moved billing because MySQL replication lagged."].id
        assert dest.lineage(cause, user_id="newuser")["edges"]
    finally:
        dest.close()


def test_import_is_idempotent(source, tmp_path):
    mem, *_ = source
    export_bundle(mem, tmp_path / "x.mem", user_id=U)
    dest = MemoryOS.in_memory()
    try:
        import_bundle(dest, tmp_path / "x.mem", user_id=U)
        again = import_bundle(dest, tmp_path / "x.mem", user_id=U)
        assert again["imported"] == 0 and again["already_present"] == 3
        assert len(dest.list_memories(user_id=U)) == 3
    finally:
        dest.close()


def test_edited_or_damaged_bundles_are_rejected(source, tmp_path):
    mem, *_ = source
    path = tmp_path / "x.mem"
    export_bundle(mem, path, user_id=U)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["memories"][0]["content"] = "The billing service uses Oracle."
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BundleError, match="sha256 mismatch"):
        read_bundle(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(BundleError):
        read_bundle(path)
    path.write_text(json.dumps({"format": "other"}), encoding="utf-8")
    with pytest.raises(BundleError, match="not a memoraos bundle"):
        read_bundle(path)


def test_signature_verifies_only_with_the_right_key_and_keeps_verified_label(source, tmp_path):
    mem, *_ = source
    path = tmp_path / "x.mem"
    assert export_bundle(mem, path, user_id=U, key="s3cret")["signed"]
    assert read_bundle(path, key="s3cret")[1] is True
    assert read_bundle(path)[1] is False
    with pytest.raises(BundleError, match="signature mismatch"):
        read_bundle(path, key="wrong")
    with pytest.raises(BundleError, match="required"):
        read_bundle(path, require_signature=True)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["signature"]["value"] = "0" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BundleError, match="signature mismatch"):
        read_bundle(path, key="s3cret")
    export_bundle(mem, path, user_id=U, key="s3cret")
    dest = MemoryOS.in_memory()
    try:
        out = import_bundle(dest, path, user_id=U, key="s3cret", require_signature=True)
        assert out["signature_verified"] and out["verified_downgraded"] == 0
        assert {m.verification for m in dest.list_memories(user_id=U)} == {"verified", "unverified", "hypothesis"}
    finally:
        dest.close()


def test_dry_run_imports_nothing(source, tmp_path):
    mem, *_ = source
    path = tmp_path / "x.mem"
    export_bundle(mem, path, user_id=U)
    dest = MemoryOS.in_memory()
    try:
        assert import_bundle(dest, path, user_id=U, dry_run=True)["imported"] == 0 and not dest.list_memories(user_id=U)
    finally:
        dest.close()


def test_cli_export_and_import_with_signing_key_from_the_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMORAOS_BUNDLE_KEY", "pw")
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    assert main(["--data-dir", a, "remember", "The cache TTL is 30 seconds.", "--user", U]) == 0
    assert main(["--data-dir", a, "export-bundle", str(tmp_path / "t.mem"), "--user", U]) == 0
    assert '"signed": true' in capsys.readouterr().out
    assert main(["--data-dir", b, "import-bundle", str(tmp_path / "t.mem"), "--user", U, "--require-signature"]) == 0
    assert '"imported": 1' in capsys.readouterr().out
    monkeypatch.delenv("MEMORAOS_BUNDLE_KEY")
    assert main(["--data-dir", b, "import-bundle", str(tmp_path / "t.mem"), "--user", U, "--require-signature"]) == 2
    assert "required" in capsys.readouterr().err
