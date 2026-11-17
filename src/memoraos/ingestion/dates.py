"""Date extraction from sentences (for fact validity) and from questions (for temporal retrieval)."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO = r"\d{4}-\d{2}-\d{2}"
_MDY = rf"\b(?:{_MONTH_RE})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
_DMY = rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_RE})\.?,?\s+\d{{4}}"
_MY = rf"\b(?:{_MONTH_RE})\.?,?\s+\d{{4}}"
_YEAR = r"(?:19|20)\d{2}"
_YM = r"\b\d{4}-(?:0[1-9]|1[0-2])(?![\d-])"
_FULL = rf"(?:{_ISO}|{_YM}|{_MDY}|{_DMY}|{_MY})"

_PREP = r"(?:from|since|in|during|as of|on|by|until|till|through|effective|starting|between|of|year)"
_PHRASE = re.compile(
    rf"(?P<comma>,\s*)?(?:\b(?P<prep>{_PREP})\s+)?(?P<d1>{_FULL}|(?<![\d₹$€£.,]){_YEAR}(?![\d,]|\.\d))"
    rf"(?:\s+(?P<sep>to|until|till|through|and|-)\s+(?P<d2>{_FULL}|(?<![\d₹$€£.,]){_YEAR}(?![\d,])))?",
    re.I,
)


@dataclass
class ParsedDate:
    iso: str
    precision: str  # day | month | year
    end_iso: str  # last instant of the covered period, as date


def _last_day(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def parse_date_expr(text: str) -> ParsedDate | None:
    t = text.strip().lower().rstrip(",.")
    if re.fullmatch(_ISO, t):
        y, m, d = int(t[:4]), int(t[5:7]), int(t[8:10])
        try:
            datetime(y, m, d)
        except ValueError:
            return None
        s = f"{y:04d}-{m:02d}-{d:02d}"
        return ParsedDate(s, "day", s)
    m = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", t)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return ParsedDate(f"{y:04d}-{mo:02d}-01", "month", f"{y:04d}-{mo:02d}-{_last_day(y, mo):02d}")
    m = re.fullmatch(rf"({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", t)
    if m:
        mo, d, y = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
        try:
            datetime(y, mo, d)
        except ValueError:
            return None
        s = f"{y:04d}-{mo:02d}-{d:02d}"
        return ParsedDate(s, "day", s)
    m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})", t)
    if m:
        d, mo, y = int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3))
        try:
            datetime(y, mo, d)
        except ValueError:
            return None
        s = f"{y:04d}-{mo:02d}-{d:02d}"
        return ParsedDate(s, "day", s)
    m = re.fullmatch(rf"({_MONTH_RE})\.?,?\s+(\d{{4}})", t)
    if m:
        mo, y = _MONTHS[m.group(1)], int(m.group(2))
        return ParsedDate(f"{y:04d}-{mo:02d}-01", "month", f"{y:04d}-{mo:02d}-{_last_day(y, mo):02d}")
    if re.fullmatch(_YEAR, t):
        y = int(t)
        return ParsedDate(f"{y:04d}-01-01", "year", f"{y:04d}-12-31")
    return None


@dataclass
class DateSpan:
    valid_from: str | None
    valid_until: str | None
    precision: str | None
    cleaned: str


_START_PREPS = {"from", "since", "in", "during", "as of", "on", "effective", "starting", "of", "year", "between", None}
_END_PREPS = {"until", "till", "through", "by"}


def extract_dates(sentence: str) -> DateSpan:
    """Pull validity dates out of a sentence and return the sentence without the date phrase."""
    valid_from = valid_until = precision = None
    spans: list[tuple[int, int]] = []
    for m in _PHRASE.finditer(sentence):
        d1 = parse_date_expr(m.group("d1"))
        if not d1:
            continue
        prep = (m.group("prep") or "").lower() or None
        d2 = parse_date_expr(m.group("d2")) if m.group("d2") else None
        bare_year = d1.precision == "year" and prep is None
        if bare_year:
            continue
        if d2:
            valid_from, valid_until, precision = d1.iso, d2.end_iso, d1.precision
        elif prep in _END_PREPS:
            valid_until, precision = d1.end_iso, d1.precision
        else:
            valid_from, precision = d1.iso, d1.precision
        spans.append((m.start(), m.end()))
    cleaned = sentence
    for a, b in reversed(spans):
        cleaned = cleaned[:a] + cleaned[b:]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;")
    return DateSpan(valid_from, valid_until, precision, cleaned)


@dataclass
class TimeRef:
    kind: str  # at | range | before | after | latest_n
    start: str | None  # ISO date
    end: str | None
    text: str


_NUM_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten twelve".split()) if w != "zero"}
_NUM_WORDS["twelve"] = 12


def parse_time_reference(query: str, now: datetime | None = None) -> TimeRef | None:
    """Detect an explicit time expression in a question."""
    now = now or datetime.now(timezone.utc)
    q = query.lower()
    m = re.search(
        rf"\b(?:(?:in|over|during|within|for) )?the (?:last|past) (\d+|{'|'.join(_NUM_WORDS)}) (year|month|week|day)s?\b", q
    )
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS[m.group(1)]
        days = {"year": 365, "month": 30, "week": 7, "day": 1}[m.group(2)] * n
        return TimeRef("range", (now - timedelta(days=days)).date().isoformat(), now.date().isoformat(), m.group(0))
    m = re.search(r"\b(?:last|past) (year|month|week)\b", q)
    if m:
        days = {"year": 365, "month": 30, "week": 7}[m.group(1)]
        return TimeRef("range", (now - timedelta(days=days)).date().isoformat(), now.date().isoformat(), m.group(0))
    m = re.search(r"\bthis year\b", q)
    if m:
        return TimeRef("range", f"{now.year}-01-01", now.date().isoformat(), m.group(0))
    kind = "at"
    for m in _PHRASE.finditer(query):
        d1 = parse_date_expr(m.group("d1"))
        if not d1:
            continue
        prep = (m.group("prep") or "").lower()
        if d1.precision == "year" and not prep:
            continue
        d2 = parse_date_expr(m.group("d2")) if m.group("d2") else None
        if d2:
            return TimeRef("range", d1.iso, d2.end_iso, m.group(0).strip())
        before = re.search(r"\bbefore\s*$", query[: m.start()].lower())
        after = re.search(r"\bafter\s*$", query[: m.start()].lower())
        if before:
            return TimeRef("before", None, d1.iso, m.group(0).strip())
        if after:
            return TimeRef("after", d1.end_iso, None, m.group(0).strip())
        return TimeRef(kind, d1.iso, d1.end_iso, m.group(0).strip())
    return None
