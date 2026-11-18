from __future__ import annotations

import pytest

from memoraos import MemoryOS
from memoraos.config import Settings
from memoraos.storage import crypto
from memoraos.storage.db import Database, convert_database

pytest.importorskip("cryptography")

PLAIN_MARKER = "Zanzibar-Quokka-Secret"


def _engine(tmp_path, passphrase):
    return MemoryOS.local(tmp_path, settings=Settings(encryption_passphrase=passphrase))


def test_file_holds_no_plaintext_and_round_trips(tmp_path):
    with _engine(tmp_path, "correct horse") as m:
        m.remember(f"Alice works at {PLAIN_MARKER} Labs.", user_id="u1")
    raw = (tmp_path / "memoraos.db").read_bytes()
    assert raw.startswith(crypto.MAGIC)
    assert PLAIN_MARKER.encode() not in raw and b"SQLite format" not in raw
    with _engine(tmp_path, "correct horse") as m:
        res = m.recall("Where does Alice work?", user_id="u1")
        assert PLAIN_MARKER in res.answer


def test_wrong_passphrase_and_missing_passphrase_are_refused(tmp_path):
    with _engine(tmp_path, "right") as m:
        m.remember("Bob lives in Lisbon.", user_id="u1")
    with pytest.raises(crypto.EncryptionError, match="Wrong passphrase"):
        _engine(tmp_path, "wrong")
    with pytest.raises(crypto.EncryptionError, match="is encrypted"):
        MemoryOS.local(tmp_path)


def test_tampered_file_fails_authentication(tmp_path):
    with _engine(tmp_path, "pw") as m:
        m.remember("Carol lives in Oslo.", user_id="u1")
    path = tmp_path / "memoraos.db"
    blob = bytearray(path.read_bytes())
    blob[-5] ^= 0x01
    path.write_bytes(bytes(blob))
    with pytest.raises(crypto.EncryptionError):
        _engine(tmp_path, "pw")


def test_plain_file_is_not_silently_opened_with_a_passphrase(tmp_path):
    with MemoryOS.local(tmp_path) as m:
        m.remember("Dave lives in Rome.", user_id="u1")
    with pytest.raises(crypto.EncryptionError, match="plain SQLite"):
        _engine(tmp_path, "pw")


def test_convert_plain_to_encrypted_and_back_keeps_data(tmp_path):
    with MemoryOS.local(tmp_path) as m:
        m.remember(f"Erin works at {PLAIN_MARKER} Labs.", user_id="u1")
    db = tmp_path / "memoraos.db"
    convert_database(db, "pw", to_encrypted=True)
    assert PLAIN_MARKER.encode() not in db.read_bytes()
    assert not (tmp_path / "memoraos.db-wal").exists()
    with _engine(tmp_path, "pw") as m:
        assert PLAIN_MARKER in m.recall("Where does Erin work?", user_id="u1").answer
    convert_database(db, "pw", to_encrypted=False)
    with MemoryOS.local(tmp_path) as m:
        assert PLAIN_MARKER in m.recall("Where does Erin work?", user_id="u1").answer


def test_each_write_uses_a_fresh_nonce_and_backup_stays_encrypted(tmp_path):
    db = Database(tmp_path / "x.db", "pw")
    first = (tmp_path / "x.db").read_bytes()
    db.execute("CREATE TABLE t(a)")
    db.execute("INSERT INTO t VALUES(1)")
    second = (tmp_path / "x.db").read_bytes()
    nonce = slice(len(crypto.MAGIC) + crypto.SALT_LEN, len(crypto.MAGIC) + crypto.SALT_LEN + crypto.NONCE_LEN)
    assert first[nonce] != second[nonce]
    dest = db.backup(tmp_path / "copy.db")
    assert crypto.is_encrypted_file(dest)
    db.close()


def test_rolled_back_transaction_is_not_persisted(tmp_path):
    db = Database(tmp_path / "x.db", "pw")
    db.execute("CREATE TABLE t(a)")
    with pytest.raises(RuntimeError), db.tx() as conn:
        conn.execute("INSERT INTO t VALUES(1)")
        raise RuntimeError("abort")
    db.close()
    again = Database(tmp_path / "x.db", "pw")
    assert again.one("SELECT COUNT(*) FROM t")[0] == 0
    again.close()


def test_document_copy_is_skipped_when_encrypted(tmp_path):
    doc = tmp_path / "note.txt"
    doc.write_text(f"Frank works at {PLAIN_MARKER} Labs.", encoding="utf-8")
    with _engine(tmp_path / "data", "pw") as m:
        m.ingest_document(doc, user_id="u1")
    assert not (tmp_path / "data" / "sources").exists()


def test_passphrase_is_never_serialised():
    s = Settings(encryption_passphrase="topsecret")
    assert "topsecret" not in repr(s) and "topsecret" not in s.model_dump_json()
