"""Bitemporal fact timelines and contradiction analysis (the "truth engine" core).

Two time axes are kept separate:
  * valid time  - when a fact was true in the world (``valid_from`` / ``valid_until``)
  * system time - when MemoraOS learned/retracted it (``recorded_at`` / ``retracted_at``)

Resolution rules for two different values of the same single-valued slot (documented in
docs/TEMPORAL_MEMORY.md):
  1. Both have explicit effective dates and differ  -> ordinary update (later wins).
  2. Same explicit effective date                    -> unresolved CONFLICT.
  3. At least one undated:
       a. versioned values of one product (Angular 16 -> 19) -> possible version change (later wins)
       b. later value has an effective date after the earlier one was recorded -> update
       c. both explicit user statements/conversation      -> later statement supersedes
       d. one value verified / the other disputed          -> the verified one wins (reported)
       e. reliability differs by >= 0.2                    -> more reliable value wins (reported)
       f. otherwise                                        -> unresolved CONFLICT (no value is chosen)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ingestion.lexicon import version_parts
from ..models import Contradiction, Fact, TimelineEntry

RELIABILITY_MARGIN = 0.2
SELF_REPORT_TYPES = {"user_statement", "conversation"}


@dataclass
class Run:
    """Consecutive assertions of the same value."""

    object_key: str
    value: str
    start: str
    explicit_start: bool
    explicit_until: str | None
    recorded_at: str
    facts: list[Fact] = field(default_factory=list)

    @property
    def memory_ids(self) -> list[str]:
        return list(dict.fromkeys(f.memory_id for f in self.facts))

    @property
    def reliability(self) -> float:
        return max(f.source_reliability for f in self.facts)

    @property
    def source_types(self) -> set[str]:
        return {f.source_type or "" for f in self.facts}

    @property
    def verification_score(self) -> int:
        if any(f.verification == "verified" for f in self.facts):
            return 1
        if all(f.verification == "disputed" for f in self.facts):
            return -1
        return 0


@dataclass
class Group:
    runs: list[Run]
    start: str

    @property
    def conflicted(self) -> bool:
        return len(self.runs) > 1


@dataclass
class Timeline:
    subject: str
    slot: str
    groups: list[Group]
    rejected: list[tuple[Run, str]]
    contradictions: list[Contradiction]

    def _group_end(self, i: int) -> str | None:
        return self.groups[i + 1].start if i + 1 < len(self.groups) else None

    def at(self, when: str) -> tuple[list[Run], bool] | None:
        """Runs valid at ``when`` (system-time filtering is already applied) and whether they conflict."""
        chosen: int | None = None
        for i, g in enumerate(self.groups):
            if g.start <= when:
                chosen = i
        if chosen is None:
            return None
        g = self.groups[chosen]
        live = [r for r in g.runs if r.explicit_until is None or r.explicit_until > when]
        if not live:
            return None
        return live, len(live) > 1

    def overlapping(self, start: str, end: str) -> list[tuple[Run, bool]]:
        """(run, conflicted) for runs whose validity overlaps [start, end)."""
        out = []
        for i, g in enumerate(self.groups):
            g_end = self._group_end(i)
            if g.start < end and (g_end is None or g_end > start):
                for r in g.runs:
                    r_end = min(x for x in (g_end, r.explicit_until) if x) if (g_end or r.explicit_until) else None
                    if r_end is None or r_end > start:
                        out.append((r, g.conflicted))
        return out

    def entries(self, when: str) -> list[TimelineEntry]:
        """Presentation form with a status for each run relative to ``when``."""
        cur = self.at(when)
        current_keys = {r.object_key for r in cur[0]} if cur else set()
        conflicted = bool(cur and cur[1])
        out: list[TimelineEntry] = []
        for i, g in enumerate(self.groups):
            end = self._group_end(i)
            for r in g.runs:
                is_current = r.object_key in current_keys and g.start <= when and (end is None or end > when)
                status = ("conflicted" if conflicted else "current") if is_current else "historical"
                out.append(
                    TimelineEntry(
                        value=r.value,
                        valid_from=r.start if r.explicit_start else None,
                        valid_until=r.explicit_until or (end if end and end > r.start else None),
                        recorded_at=r.recorded_at,
                        status=status,  # type: ignore[arg-type]
                        memory_ids=r.memory_ids,
                        source_reliability=r.reliability,
                        inferred_start=not r.explicit_start,
                    )
                )
        for r, why in self.rejected:
            out.append(
                TimelineEntry(
                    value=r.value, valid_from=r.start if r.explicit_start else None, valid_until=None,
                    recorded_at=r.recorded_at, status="historical", memory_ids=r.memory_ids,
                    source_reliability=r.reliability, inferred_start=not r.explicit_start, note=why,
                )
            )
        return out


def _effective(f: Fact) -> tuple[str, bool]:
    return (f.valid_from, True) if f.valid_from else (f.recorded_at, False)


def _relation(a: Run, b: Run, slot: str) -> tuple[str, str, str]:
    """Return (kind, resolved_value_side, justification) for earlier run a and later run b.

    kind in: update | possible_version_change | resolved_by_reliability | reject_later | conflict
    """
    if a.explicit_until and a.explicit_until <= b.start:
        return "update", "later", "earlier value had an explicit end date"
    if a.explicit_start and b.explicit_start:
        if a.start < b.start:
            return "update", "later", "later effective date"
        return "conflict", "none", "two different values share the same effective date"
    if b.explicit_start and b.start > a.start:
        return "update", "later", "the later value carries an effective date after the earlier value was recorded"
    if slot.startswith(("uses:", "depends_on:")) and version_parts(a.value) and version_parts(b.value):
        return "possible_version_change", "later", "same product with a different version; treated as a version change"
    if a.source_types <= SELF_REPORT_TYPES and b.source_types <= SELF_REPORT_TYPES:
        return "update", "later", "later self-reported statement supersedes the earlier one"
    sa, sb = a.verification_score, b.verification_score
    if sb > sa:
        return "resolved_by_reliability", "later", "the later value is verified (or the earlier one is disputed)"
    if sa > sb:
        return "reject_later", "earlier", "the earlier value is verified (or the later one is disputed)"
    gap = b.reliability - a.reliability
    if gap >= RELIABILITY_MARGIN:
        return "resolved_by_reliability", "later", f"later value comes from a more reliable source (+{gap:.2f})"
    if -gap >= RELIABILITY_MARGIN:
        return "reject_later", "earlier", f"earlier value comes from a more reliable source ({-gap:.2f} higher)"
    return "conflict", "none", "different values from comparably reliable sources with no effective dates to order them"


def build_timeline(facts: list[Fact]) -> Timeline:
    """Build the timeline for facts of one (subject, slot). Facts must already be system-time filtered."""
    if not facts:
        raise ValueError("no facts")
    subject, slot = facts[0].subject, facts[0].slot or facts[0].predicate
    # Input arrives in insertion (rowid) order and Python's sort is stable, so ties on (effective time,
    # recorded_at) keep the order in which facts were stored. Never tie-break on the random fact id: on
    # coarse clocks (Windows ~15 ms) back-to-back facts share a timestamp and the id would pick the
    # "latest" value at random.
    ordered = sorted(facts, key=lambda f: (_effective(f)[0], f.recorded_at))
    runs: list[Run] = []
    for f in ordered:
        eff, explicit = _effective(f)
        if runs and runs[-1].object_key == f.object_key:
            r = runs[-1]
            r.facts.append(f)
            if f.valid_until:
                r.explicit_until = f.valid_until
            continue
        runs.append(Run(f.object_key, f.object, eff, explicit, f.valid_until, f.recorded_at, [f]))

    groups: list[Group] = [Group([runs[0]], runs[0].start)]
    rejected: list[tuple[Run, str]] = []
    contradictions: list[Contradiction] = []
    for run in runs[1:]:
        last_run = groups[-1].runs[-1]
        kind, side, why = _relation(last_run, run, slot)
        ids = list(dict.fromkeys(last_run.memory_ids + run.memory_ids))
        values = [last_run.value, run.value]
        if kind in ("update",):
            groups.append(Group([run], run.start))
        elif kind in ("possible_version_change", "resolved_by_reliability"):
            groups.append(Group([run], run.start))
            contradictions.append(Contradiction(subject=subject, slot=slot, values=values, kind=kind, resolved=True, justification=why, memory_ids=ids, since=run.recorded_at))
        elif kind == "reject_later":
            rejected.append((run, why))
            contradictions.append(Contradiction(subject=subject, slot=slot, values=values, kind="resolved_by_reliability", resolved=True, justification=f"kept '{last_run.value}': {why}", memory_ids=ids, since=run.recorded_at))
        else:
            groups[-1].runs.append(run)
            groups[-1].start = min(groups[-1].start, run.start)
            contradictions.append(Contradiction(subject=subject, slot=slot, values=values, kind="conflict", resolved=False, justification=why, memory_ids=ids, since=run.recorded_at))
    # a conflict is only open while it is still the latest group
    for c in contradictions:
        if c.kind == "conflict" and not (groups[-1].conflicted and set(c.values) <= {r.value for r in groups[-1].runs}):
            c.resolved = True
            c.justification += "; later superseded by a newer value"
    return Timeline(subject, slot, groups, rejected, contradictions)
