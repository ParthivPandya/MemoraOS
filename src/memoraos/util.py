"""Small shared helpers: time, ids, hashing, tokenization."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]

TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ts(dt: datetime) -> str:
    """Fixed-width UTC timestamp; lexicographic order equals chronological order."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(TS_FORMAT)


def parse_ts(value: str) -> datetime:
    """Parse a stored timestamp or a user-supplied ISO date / datetime (naive means UTC)."""
    v = value.strip()
    if re.fullmatch(r"\d{4}", v):
        return datetime(int(v), 1, 1, tzinfo=timezone.utc)
    if re.fullmatch(r"\d{4}-\d{2}", v):
        return datetime(int(v[:4]), int(v[5:7]), 1, tzinfo=timezone.utc)
    v = v.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_ts(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ts(value)
    return ts(parse_ts(value))


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_WORD = re.compile(r"[A-Za-z0-9_#+.\-]*[A-Za-z0-9_#+]|[₹$€£]")

STOPWORDS = frozenset(
    """a an the and or but if then else of for to in on at by with from as is are was were be been being am do does
    did done have has had having i me my mine we our us you your he she it its they them their this that these
    those there here what which who whom whose when where why how can could should would will shall may might must
    about into over under than also not no yes any all some each tell please give show me know explain describe
    list find get happen happened happens happening""".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens (keeps things like c#, node.js, angular-19)."""
    out = []
    for m in _WORD.finditer(text.lower()):
        tok = m.group(0).strip(".-")
        if tok:
            out.append(tok)
    return out


def stem(token: str) -> str:
    """Very small suffix stripper; deterministic and dependency free."""
    t = token
    if len(t) <= 3 or any(ch.isdigit() for ch in t):
        return t
    for suf in ("ingly", "edly", "ing", "ies", "ied", "ed", "es", "s", "ly"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            base = t[: -len(suf)]
            if suf in ("ies", "ied"):
                return base + "y"
            if suf in ("ing", "ed") and len(base) >= 4 and base[-1] == base[-2] and base[-1] not in "ls":
                base = base[:-1]
            return base
    return t


def content_terms(text: str) -> list[str]:
    """Stemmed non-stopword terms, order preserved, duplicates removed."""
    seen: dict[str, None] = {}
    for tok in tokenize(text):
        if tok in STOPWORDS or (len(tok) < 2 and not tok.isdigit()):
            continue
        seen.setdefault(stem(tok), None)
    return list(seen)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token); documented approximation."""
    return max(1, (len(text) + 3) // 4) if text else 0
