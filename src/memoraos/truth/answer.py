"""Evidence-grounded answer construction (no LLM required).

Fact answers come from bitemporal timelines. Passage answers are extractive: the best-matching
sentence(s) of retrieved memories. If the evidence does not cover enough of the question, the
result is ``insufficient_evidence`` instead of a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..ingestion.lexicon import PREDICATE_SYNONYMS
from ..models import Contradiction, Fact, TimelineEntry
from ..providers.local import split_sentences
from ..retrieval.facts import SlotQuery
from ..routing.router import QueryFeatures
from ..security import detect_prompt_injection
from ..util import parse_ts, stem, to_ts, tokenize
from .timeline import Run, Timeline, build_timeline

_SYNONYM_GROUPS = [{stem(w) for w in words} | {stem(p.replace("_", " ").split()[0])} for p, words in PREDICATE_SYNONYMS.items()]


@dataclass
class FactAnswer:
    text: str
    status: str  # answered | conflict | insufficient_evidence
    facts: list[Fact] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    temporal_validity: str = "not_applicable"
    extraction_confidence: float | None = None
    source_reliability: float | None = None


def _label(predicate: str) -> str:
    return predicate.split(":")[0].replace("_", " ")


def _date(iso: str | None) -> str | None:
    return iso[:10] if iso else None


def _describe(run: Run) -> str:
    return run.value + (f" (effective {_date(run.start)})" if run.explicit_start else "")


def _group_facts(facts: list[Fact], reverse: bool) -> dict[tuple, list[Fact]]:
    groups: dict[tuple, list[Fact]] = {}
    for f in facts:
        if reverse:
            key = (f.object_key, f.predicate, f.subject_key)
        elif f.slot:
            key = (f.subject_key, f.slot)
        else:
            key = (f.subject_key, f.predicate, f.object_key)
        groups.setdefault(key, []).append(f)
    return groups


def resolve_facts(sq: SlotQuery, feats: QueryFeatures, now_iso: str) -> FactAnswer:
    """Turn matched facts into an answer honouring current / at-date / previous / history questions."""
    tref = feats.time_ref
    when = now_iso
    window: tuple[str, str] | None = None
    if tref and tref.kind in ("at", "range") and tref.start and tref.end:
        window = (to_ts(tref.start), _end_of_day(tref.end))
        when = min(now_iso, window[1])
    elif tref and tref.kind == "before" and tref.end:
        when = to_ts(tref.end)
    elif tref and tref.kind == "after" and tref.start:
        when = _end_of_day(tref.start)

    groups = _group_facts(sq.facts, sq.reverse)
    # multi-valued groups collapse into one answer per (subject, predicate)
    slot_groups: dict[tuple, list[Timeline]] = {}
    timelines: list[Timeline] = []
    for key, fs in groups.items():
        tl = build_timeline(fs)
        timelines.append(tl)
        slot_groups.setdefault(key[:2] if len(key) == 2 else (key[0], key[1]), []).append(tl)

    all_contradictions = [c for tl in timelines for c in tl.contradictions]
    lines: list[tuple[str, str]] = []
    used: list[Fact] = []
    entries: list[TimelineEntry] = []
    conflicted = False
    validity = "not_applicable"
    open_conflicts: list[Contradiction] = []

    for (_, _), tls in slot_groups.items():
        values: list[str] = []
        subject = tls[0].subject
        pred = _label(tls[0].slot if tls[0].slot else tls[0].groups[0].runs[0].facts[0].predicate)
        pred_raw = tls[0].groups[0].runs[0].facts[0].predicate
        for tl in tls:
            entries.extend(tl.entries(when))
            if sq.reverse:
                cur = tl.at(when)
                if cur:
                    values.append(tl.subject)
                    used.extend(r.facts[-1] for r in cur[0])
                    validity = "current"
                continue
            if feats.history_ref and not tref and not feats.previous_ref:
                seq = [r for g in tl.groups for r in g.runs]
                values.append(" -> ".join(_describe(r) for r in seq))
                used.extend(f for r in seq for f in r.facts[-1:])
                validity = "historical"
                continue
            if feats.previous_ref and len(tl.groups) >= 2:
                prev = tl.groups[-2]
                values.extend(r.value for r in prev.runs)
                used.extend(r.facts[-1] for r in prev.runs)
                validity = "historical"
                continue
            if feats.previous_ref and len(tl.groups) < 2:
                lines.append((f"Earlier {pred} of {subject}", "none recorded"))
                continue
            if window:
                hits = tl.overlapping(*window)
                if hits:
                    latest_group_conflict = hits[-1][1]
                    chosen = [r for r, _c in hits[-(len(hits) if latest_group_conflict else 1):]]
                    values.extend(r.value for r in chosen)
                    used.extend(r.facts[-1] for r in chosen)
                    conflicted |= latest_group_conflict
                    validity = "conflicted" if latest_group_conflict else "historical"
                continue
            cur = tl.at(when)
            if cur:
                runs, is_conflict = cur
                values.extend(r.value if not r.explicit_start or not tref else _describe(r) for r in runs)
                used.extend(r.facts[-1] for r in runs)
                if is_conflict:
                    conflicted = True
                    open_conflicts.extend(c for c in tl.contradictions if c.kind == "conflict" and not c.resolved)
                    validity = "conflicted"
                elif validity != "conflicted":
                    last = runs[0]
                    historical = tref is not None and tref.kind in ("before",)
                    validity = "historical" if historical else ("current" if last.explicit_start else "undated")
        if not values:
            continue
        uniq = list(dict.fromkeys(values))
        if sq.reverse:
            obj = tls[0].groups[0].runs[0].facts[0].object
            lines.append((f"{pred_raw.replace('_', ' ')} {obj}", ", ".join(uniq)))
        else:
            who = "Your" if subject.lower() in ("i", "user", "me", "my") or tls[0].groups[0].runs[0].facts[0].subject_key == "user" else f"{subject}'s"
            sep = " | " if conflicted else ", "
            lines.append((f"{who} {pred}", sep.join(uniq)))

    if not lines:
        return FactAnswer("", "insufficient_evidence", contradictions=all_contradictions)
    if len(lines) == 1:
        rendered = lines[0][1]
    else:
        rendered = "; ".join(f"{label}: {val}" for label, val in lines)
    if conflicted:
        text = "The memory contains conflicting values and does not establish which is correct: " + rendered
        return FactAnswer(text, "conflict", used, entries, all_contradictions, "conflicted", _min_conf(used), _max_rel(used))
    return FactAnswer(rendered, "answered", used, entries, all_contradictions, validity, _min_conf(used), _max_rel(used))


def _end_of_day(iso: str) -> str:
    d = parse_ts(iso)
    return to_ts(datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=d.tzinfo))


def _min_conf(fs: list[Fact]) -> float | None:
    return min((f.extraction_confidence for f in fs), default=None)


def _max_rel(fs: list[Fact]) -> float | None:
    return max((f.source_reliability for f in fs), default=None)


# ---------------------------------------------------------------------------------------------
# passage answers
# ---------------------------------------------------------------------------------------------
def covered_terms(query_terms: list[str], text: str) -> set[str]:
    stems = {stem(t) for t in tokenize(text)}
    covered = set()
    for q in query_terms:
        if q in stems:
            covered.add(q)
            continue
        for grp in _SYNONYM_GROUPS:
            if q in grp and stems & grp:
                covered.add(q)
                break
    return covered


@dataclass
class PassageAnswer:
    text: str
    sentences: list[tuple[str, str]]  # (memory_id, sentence)
    coverage: float
    flags: list[str]
    covered: set[str] = field(default_factory=set)


def compose_passage_answer(terms: list[str], passages: list[tuple[str, str]], *, max_sentences: int = 1, whole_passage: bool = False) -> PassageAnswer:
    """passages: ordered (memory_id, text). Pick the sentence(s) covering the most query terms."""
    if not passages or not terms:
        return PassageAnswer("", [], 0.0, [])
    flags: list[str] = []
    scored: list[tuple[float, int, int, str, str]] = []
    for rank, (mid, text) in enumerate(passages):
        if detect_prompt_injection(text):
            flags.append("possible_prompt_injection")
        for si, sent in enumerate(split_sentences(text)):
            if detect_prompt_injection(sent):
                continue
            cov = covered_terms(terms, sent)
            if cov:
                scored.append((len(cov) / len(terms), -rank, -si, mid, sent))
    flags = list(dict.fromkeys(flags))
    if not scored:
        return PassageAnswer("", [], 0.0, flags)
    scored.sort(reverse=True)
    if whole_passage:
        mid = scored[0][3]
        text = next(t for m, t in passages if m == mid)
        cov_set = covered_terms(terms, text)
        return PassageAnswer(text, [(mid, text)], len(cov_set) / len(terms), flags, cov_set)
    chosen: list[tuple[str, str]] = []
    seen_text: set[str] = set()
    covered: set[str] = set()
    for _c, _r, _s, mid, sent in scored:
        if sent in seen_text:
            continue
        new = covered_terms(terms, sent) - covered
        if chosen and not new:
            continue
        chosen.append((mid, sent))
        seen_text.add(sent)
        covered |= covered_terms(terms, sent)
        if len(chosen) >= max_sentences:
            break
    return PassageAnswer(" ".join(s for _, s in chosen), chosen, len(covered) / len(terms), flags, covered)
