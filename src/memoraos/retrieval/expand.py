"""Query expansion. The original question is ALWAYS kept as the first, full-weight query.

Expansions only add recall; they are weighted below the original and never replace it, so an expansion that
turns out to be noise can lower a rank but cannot remove the original match.

* deterministic: aliases the memory already knows, predicate hints ("how much ... make" -> salary), and
  decomposition of compound questions;
* optional: an LLM paraphrase that is validated (it must keep every entity and number of the original).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..providers.base import ChatProvider
from ..security import detect_prompt_injection

_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bhow much\b.*\b(?:make|makes|earn|earns|paid|get|gets|drawn?)\b", re.I), "salary", "'how much ... make' asks about salary"),
    (re.compile(r"\bwhat(?:'s| is| are)? (?:the |his |her |their |my )?(?:pay|ctc|package|income|compensation)\b", re.I), "salary", "pay/CTC/package are salary synonyms"),
    (re.compile(r"\bwhere\b.*\b(?:stay|stays|staying|based|located|reside|resides|settled)\b", re.I), "lives in", "'where ... stay/based' asks about residence"),
    (re.compile(r"\bwhere\b.*\b(?:employed|employer)\b", re.I), "works at", "'where ... employed' asks about employer"),
    (re.compile(r"\bwho\b.*\b(?:runs|heads|oversees|owns|in charge of|responsible for)\b", re.I), "leads", "'who runs/heads/owns' asks about the lead"),
    (re.compile(r"\bwhich\b.*\b(?:region|datacenter|data center)\b", re.I), "hosted in", "'which region' asks where something is hosted"),
]
_QUESTION_WORD = re.compile(r"\b(?:what|who|where|when|which|how|why)\b", re.I)
_SPLIT = re.compile(r"\s*(?:,|;|\band\b|\balso\b)\s+(?=(?:what|who|where|when|which|how|why)\b)", re.I)


@dataclass
class Variant:
    text: str
    reason: str
    weight: float = 0.5


@dataclass
class Expansion:
    original: str
    variants: list[Variant] = field(default_factory=list)
    predicate_hints: list[str] = field(default_factory=list)

    @property
    def queries(self) -> list[Variant]:
        """Original first (weight 1.0), then expansions."""
        return [Variant(self.original, "original", 1.0), *self.variants]


def predicate_hints(query: str) -> list[tuple[str, str]]:
    return [(term, why) for rx, term, why in _HINTS if rx.search(query)]


def decompose(query: str) -> list[str]:
    """"What is X, and where does Y live?" -> two sub-questions. A single question is returned unchanged."""
    parts = [p.strip(" ?,.;") for p in _SPLIT.split(query.strip()) if p.strip(" ?,.;")]
    if len(parts) > 1 and all(_QUESTION_WORD.search(p) and len(p.split()) >= 3 for p in parts):
        return [p + "?" for p in parts[:4]]
    return [query]


def _must_keep(query: str) -> set[str]:
    """Tokens a faithful paraphrase has to keep: capitalised names (past the first word) and numbers."""
    toks = set(re.findall(r"\d[\w.,]*", query))
    toks |= {w.lower() for i, w in enumerate(re.findall(r"[A-Za-z][\w.#+\-]*", query)) if w[0].isupper() and i > 0}
    return toks


def validate_rewrite(original: str, rewrite: str) -> bool:
    if not rewrite or len(rewrite) > 300 or rewrite.strip().lower() == original.strip().lower() or detect_prompt_injection(rewrite):
        return False
    low = rewrite.lower()
    return all(t.lower() in low for t in _must_keep(original))


def expand_query(
    query: str, *, aliases: dict[str, str] | None = None, chat: ChatProvider | None = None, use_llm: bool = False,
    on_usage: Callable | None = None, max_variants: int = 4,
) -> Expansion:
    exp = Expansion(original=query)
    seen = {query.strip().lower()}

    def add(text: str, reason: str, weight: float = 0.5) -> None:
        key = text.strip().lower()
        if key and key not in seen and len(exp.variants) < max_variants:
            seen.add(key)
            exp.variants.append(Variant(text.strip(), reason, weight))

    for term, why in predicate_hints(query):
        exp.predicate_hints.append(term)
        add(f"{query} {term}", why)
    for alias, canonical in (aliases or {}).items():
        if alias and re.search(rf"\b{re.escape(alias)}\b", query, re.I) and canonical != alias:
            add(re.sub(rf"\b{re.escape(alias)}\b", canonical, query, flags=re.I), f"alias '{alias}' -> '{canonical}'")
    subs = decompose(query)
    if len(subs) > 1:
        for s in subs:
            add(s, "sub-question", 0.7)
    if use_llm and chat is not None:
        try:
            resp = chat.complete(
                [
                    {"role": "system", "content": "Rewrite the search question in up to 2 different wordings, one per line. Keep every name and number exactly. Output only the rewrites."},
                    {"role": "user", "content": query},
                ],
                max_tokens=120,
            )
            if on_usage and getattr(resp, "usage", None):
                on_usage(resp.usage)
            for line in resp.text.splitlines()[:2]:
                line = line.strip(" -*\t0123456789.)")
                if validate_rewrite(query, line):
                    add(line, "validated LLM paraphrase")
        except Exception:  # noqa: BLE001 - an optional rewrite must never break retrieval
            pass
    return exp
