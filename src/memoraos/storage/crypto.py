"""Authenticated encryption of the database file at rest (AES-256-GCM, scrypt-derived key).

File layout: ``MAGIC (8) | salt (16) | nonce (12) | ciphertext+tag``. The header (magic and salt) is bound to the
ciphertext as associated data, so a tampered file or a wrong passphrase fails authentication instead of yielding
garbage. A fresh random nonce is used for every write.
"""

from __future__ import annotations

import os
from pathlib import Path

MAGIC = b"MOSENC01"
SALT_LEN = 16
NONCE_LEN = 12
_SCRYPT = {"n": 2**15, "r": 8, "p": 1}
ENV_KEY = "MEMORAOS_ENCRYPTION_KEY"


class EncryptionError(RuntimeError):
    """Raised for a missing extra, a wrong passphrase, a tampered file, or a plain/encrypted mismatch."""


def _crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:
        raise EncryptionError("Encryption at rest needs the extra: pip install 'memoraos[encryption]'") from exc
    return AESGCM, Scrypt


def is_encrypted_file(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    with p.open("rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def derive_key(passphrase: str, salt: bytes) -> bytes:
    _, scrypt = _crypto()
    return scrypt(salt=salt, length=32, **_SCRYPT).derive(passphrase.encode("utf-8"))


def new_salt() -> bytes:
    return os.urandom(SALT_LEN)


def encrypt(key: bytes, salt: bytes, plaintext: bytes) -> bytes:
    aesgcm, _ = _crypto()
    nonce = os.urandom(NONCE_LEN)
    return MAGIC + salt + nonce + aesgcm(key).encrypt(nonce, plaintext, MAGIC + salt)


def read_salt(blob: bytes) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + SALT_LEN + NONCE_LEN + 16:
        raise EncryptionError("Not a MemoraOS encrypted database (bad header).")
    return blob[len(MAGIC) : len(MAGIC) + SALT_LEN]


def decrypt(key: bytes, blob: bytes) -> bytes:
    aesgcm, _ = _crypto()
    salt = read_salt(blob)
    nonce = blob[len(MAGIC) + SALT_LEN : len(MAGIC) + SALT_LEN + NONCE_LEN]
    body = blob[len(MAGIC) + SALT_LEN + NONCE_LEN :]
    try:
        return aesgcm(key).decrypt(nonce, body, MAGIC + salt)
    except Exception as exc:  # cryptography raises InvalidTag, which carries no message
        raise EncryptionError("Wrong passphrase, or the encrypted database file was modified.") from exc


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
