"""Deterministic value normalisation (money, Indian number words, periods).

The canonical ``key`` is what makes "32 LPA", "32 lakhs annually" and "₹32 lakh per annum" the same value.
Two values merge only when amount, currency AND period all match; an unknown currency or period is kept as
unknown and never merges with a known one. Embedding similarity is never used to decide equality.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MULTIPLIERS = {
    "k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "lpa": 1e5,
    "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6, "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
}
_CURRENCY_SYMBOLS = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}
_INDIAN_TERMS = {"lakh", "lakhs", "lac", "lacs", "lpa", "crore", "crores", "cr"}
_CURRENCY_WORDS = {
    "rs": "INR", "inr": "INR", "rupee": "INR", "rupees": "INR",
    "usd": "USD", "dollar": "USD", "dollars": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
}
_PERIODS = {
    "annual": "annual", "annually": "annual", "annum": "annual", "yearly": "annual", "year": "annual", "yr": "annual",
    "pa": "annual", "monthly": "monthly", "month": "monthly", "mo": "monthly",
    "hourly": "hourly", "hour": "hourly", "hr": "hourly",
}
_FILLER = {
    "approximately", "about", "around", "roughly", "nearly", "of", "a", "an", "the", "per", "p", "each", "every",
    "only", "just", "ctc", "net", "gross", "in", "hand",
}
# Predicates whose bare numbers are money.
MONEY_PREDICATES = {"salary", "budget", "cost", "price", "revenue", "fee", "bonus", "stipend", "rent", "funding", "valuation", "income"}
# Predicates where a stated period matters and monthly figures are annualised for comparison.
COMPENSATION_PREDICATES = {"salary", "bonus", "stipend", "income", "ctc"}

_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?|[A-Za-z]+|[₹$€£/]")
_GAP_OK = re.compile(r"^[\s,.\-]*$")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class ParsedValue:
    amount: float  # whole currency units; annualised for compensation
    currency: str  # ISO-ish code, or "?" when unknown
    period: str  # annual | monthly | hourly | none | ?
    key: str  # canonical equality key
    kind: str = "money"


def _tokenise(text: str) -> list[str] | None:
    """Tokens of ``text``, or None when anything other than whitespace/punctuation lies between them."""
    pos, out = 0, []
    for m in _TOKEN.finditer(text):
        if not _GAP_OK.match(text[pos : m.start()]):
            return None
        out.append(m.group(0))
        pos = m.end()
    return out if _GAP_OK.match(text[pos:]) else None


def parse_value(obj: str, predicate: str = "", context: str = "") -> ParsedValue | None:
    """Parse a monetary value, or return None when ``obj`` is not (only) a number with units.

    ``predicate`` and ``context`` are consulted for the period ("annual compensation") and to decide whether a
    bare number is money. The whole string must be consumed so "Angular 16" or "Route 66 bypass" never parse.
    """
    text = obj.strip()
    if not text or len(text) > 60:
        return None
    tokens = _tokenise(text)
    if not tokens:
        return None
    pred = predicate.lower().replace("_", " ").strip()
    pred_head = pred.split()[-1] if pred else ""
    money_pred = pred_head in MONEY_PREDICATES or pred in MONEY_PREDICATES
    amount: float | None = None
    mult = 1.0
    currency: str | None = None
    period: str | None = None
    saw_marker = False
    indian_numbering = False
    for tok in tokens:
        low = tok.lower()
        if tok in _CURRENCY_SYMBOLS:
            currency, saw_marker = _CURRENCY_SYMBOLS[tok], True
        elif _NUM.fullmatch(tok):
            if amount is not None:
                return None
            amount = float(tok.replace(",", ""))
        elif low in _MULTIPLIERS:
            if amount is None and low != "lpa":
                return None
            mult *= _MULTIPLIERS[low]
            saw_marker = True
            indian_numbering = indian_numbering or low in _INDIAN_TERMS
            if low == "lpa":
                period, currency = period or "annual", currency or "INR"
        elif low in _CURRENCY_WORDS:
            currency, saw_marker = _CURRENCY_WORDS[low], True
        elif low in _PERIODS:
            period = _PERIODS[low]
        elif low in _FILLER or tok == "/":
            continue
        else:
            return None
    if amount is None or not (saw_marker or money_pred):
        return None
    if currency is None and indian_numbering:
        # lakh / crore / LPA are Indian numbering terms and denote rupees; any explicit currency still wins.
        currency = "INR"
    if period is None:
        ctx = f"{pred} {context}".lower()
        for word, canon in _PERIODS.items():
            if re.search(rf"\b{word}\b", ctx):
                period = canon
                break
    total = amount * mult
    compensation = pred_head in COMPENSATION_PREDICATES or pred in COMPENSATION_PREDICATES
    if compensation and period == "monthly":
        total, period = total * 12, "annual"
    if not compensation and period is None:
        period = "none"  # a budget or price is a lump sum; only compensation has a meaningful period
    cur, per = currency or "?", period or "?"
    amt = f"{total:.2f}".removesuffix(".00")
    return ParsedValue(amount=total, currency=cur, period=per, key=f"money:{cur}:{per}:{amt}")


def value_key(obj: str, predicate: str = "", context: str = "") -> str | None:
    pv = parse_value(obj, predicate, context)
    return pv.key if pv else None
