"""API key authentication. Keys are stored only as SHA-256 hashes and bound to one tenant and role."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

ROLES = {"read": 1, "write": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    role: str
    users: tuple[str, ...]  # ("*",) means any user id inside the tenant
    fingerprint: str

    def can(self, needed: str) -> bool:
        return ROLES[self.role] >= ROLES[needed]

    def may_act_as(self, user_id: str) -> bool:
        return "*" in self.users or user_id in self.users


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ApiKeyStore:
    def __init__(self, entries: dict[str, dict] | None = None):
        # entries: sha256(key) -> {tenant, role, users}
        self._entries: dict[str, dict] = {}
        for digest, spec in (entries or {}).items():
            self._validate(spec)
            self._entries[digest] = spec

    @staticmethod
    def _validate(spec: dict) -> None:
        if spec.get("role") not in ROLES:
            raise ValueError(f"role must be one of {sorted(ROLES)}")
        if not spec.get("tenant"):
            raise ValueError("tenant is required")

    @classmethod
    def from_plain(cls, keys: dict[str, dict]) -> ApiKeyStore:
        return cls({_hash(k): v for k, v in keys.items()})

    @classmethod
    def load(cls, path: Path | None = None, env: str = "MEMORAOS_API_KEYS") -> ApiKeyStore:
        entries: dict[str, dict] = {}
        if path and Path(path).exists():
            entries.update(json.loads(Path(path).read_text(encoding="utf-8")))
        raw = os.environ.get(env)
        if raw:
            entries.update({_hash(k): v for k, v in json.loads(raw).items()})
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def authenticate(self, presented: str | None) -> Principal | None:
        if not presented:
            return None
        digest = _hash(presented)
        found = None
        for stored, spec in self._entries.items():  # constant-time comparison across all entries
            if hmac.compare_digest(stored, digest):
                found = spec
        if not found:
            return None
        return Principal(found["tenant"], found["role"], tuple(found.get("users", ["*"])), digest[:8])

    @staticmethod
    def create(path: Path, tenant: str, role: str = "write", users: list[str] | None = None) -> str:
        """Generate a key, persist only its hash, and return the plaintext once."""
        spec = {"tenant": tenant, "role": role, "users": users or ["*"]}
        ApiKeyStore._validate(spec)
        key = "mos_" + secrets.token_urlsafe(32)
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        entries[_hash(key)] = spec
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return key
