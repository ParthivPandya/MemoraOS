"""Memory category heuristics and document chunking."""

from __future__ import annotations

import re

from ..providers.local import split_sentences

_PROCEDURAL = [
    re.compile(p, re.I | re.M)
    for p in (
        r"^\s*(?:to|how to) \w+",
        r"\b(?:steps?|procedure|runbook|workflow|playbook|checklist)\s*:",
        r"^\s*(?:\d+[.)]|[-*])\s+\w+",
        r"\bfirst,?\b.*\bthen\b",
        r"`[^`]+`",
    )
]
_IMPERATIVE_START = re.compile(r"^(?:run|install|deploy|open|click|restart|configure|execute|set|create|add|remove|use|check|verify|push|build|start|stop)\b", re.I)
_EPISODIC = re.compile(
    r"\b(?:yesterday|today|last (?:week|month|year|night)|ago|earlier|this morning|"
    r"we (?:decided|deployed|completed|finished|shipped|released|launched|fixed|discussed|met|agreed|started|migrated|failed)|"
    r"(?:deployment|migration|launch|release|build|project|test|sprint|meeting)s? (?:failed|succeeded|completed|started|was|were)|"
    r"(?:failed|crashed|outage|incident|rolled back|resolved))\b",
    re.I,
)


def classify_category(text: str, source_type: str) -> str:
    sentences = split_sentences(text)
    imperative = sum(1 for s in sentences if _IMPERATIVE_START.match(s))
    marks = sum(1 for p in _PROCEDURAL if p.search(text))
    if (imperative >= 2 and len(sentences) >= 2) or marks >= 2 or re.match(r"^\s*how to\b", text, re.I):
        return "procedural"
    if source_type == "conversation" or _EPISODIC.search(text):
        return "episodic"
    return "semantic"


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """Paragraph/sentence aware chunking. Short text yields a single chunk."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(split_sentences(para))
    chunks: list[str] = []
    cur = ""
    last_unit = ""
    for u in units:
        if len(u) > max_chars:  # one enormous sentence: hard split
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(u[i : i + max_chars] for i in range(0, len(u), max_chars - overlap))
            last_unit = ""
            continue
        if cur and len(cur) + len(u) + 1 > max_chars:
            chunks.append(cur)
            # overlap is carried as a WHOLE preceding unit (never a character-sliced fragment), and only if it fits
            tail = last_unit if overlap and len(last_unit) <= overlap and len(last_unit) + len(u) + 1 <= max_chars else ""
            cur = f"{tail}\n{u}".strip() if tail else u
        else:
            cur = f"{cur}\n{u}".strip() if cur else u
        last_unit = u
    if cur:
        chunks.append(cur)
    return chunks
