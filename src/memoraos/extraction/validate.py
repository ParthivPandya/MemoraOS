"""Grounding checks applied to every proposed fact before it can enter memory.

A model may *propose*; only text that is really in the source can *support*. Each check names the reason it
rejects, and rejections are kept in the extraction attempt log rather than discarded silently.
"""

from __future__ import annotations

import re

from ..ingestion.extract import FIRST_PERSON, ExtractedFact, norm_entity
from ..ingestion.lexicon import PREDICATE_SYNONYMS, predicate_tokens, query_stems
from ..security import detect_prompt_injection
from ..util import stem

MAX_FIELD_CHARS = 200
_PRONOUNS = {"it", "this", "that", "they", "he", "she", "there", "these", "those", "which", "who", "what", "its", "their", "his", "her", "them"}
_NEGATION_CUE = re.compile(r"\b(?:not|never|no longer|cannot|can't)\b|n['’]t\b", re.I)
_FIRST_PERSON_CUE = re.compile(r"\b(?:i|my|me|we|our|us|mine|myself|i'm|i've)\b", re.I)
_PREDICATE_OK = re.compile(r"^[a-z][a-z0-9_ ]{0,39}$")
# verbs that justify a canonical predicate but are too generic to be question synonyms
_EXTRA_CUES = {
    "salary": {"make", "made", "paid"}, "works_at": {"hired", "hire", "work"}, "lives_in": {"live", "base", "stay"},
    "leads": {"head", "run", "ran"}, "uses": {"built", "written", "run", "ran", "adopt"}, "hosted_in": {"deployed", "run", "ran"},
}


class GroundingError(ValueError):
    """Raised by callers that prefer an exception over a rejection reason."""


def _norm(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", s.lower())


def _tokens(s: str) -> list[str]:
    return [t.strip(".") for t in re.findall(r"[\w#+.]+", _norm(s)) if t.strip(".")]


_CUE_STOP = {"to", "in", "at", "of", "is", "by", "on", "with", "for", "from", "as", "the", "a", "an"}


def _loose(stems: set[str]) -> set[str]:
    """The stemmer keeps a trailing 'e' on some forms ("relocate"/"relocat"); compare without it."""
    return {s.rstrip("e") for s in stems}


def predicate_cue_present(predicate: str, span: str) -> bool:
    base = predicate.split(":")[0].replace(" ", "_")
    cues = {stem(w) for w in PREDICATE_SYNONYMS.get(base, set())}
    cues |= {stem(w) for w in _EXTRA_CUES.get(base, set())}
    cues |= {t for t in predicate_tokens(base) if t not in _CUE_STOP}
    return bool(_loose(query_stems(span)) & _loose(cues))


def validate_fact(fact: ExtractedFact, text: str, *, strict: bool = True) -> str | None:
    """Return the reason a fact is NOT supported by ``text``, or None when it is.

    ``strict`` additionally requires a lexical cue for the predicate inside the cited span, which is what stops
    a model from inventing relations ("married to", "lives in") that the source never states.
    """
    if fact.polarity not in ("affirmed", "negated"):
        return "bad_polarity"
    for name in ("subject", "predicate", "object"):
        value = getattr(fact, name)
        if not value or not str(value).strip():
            return f"empty_{name}"
        if len(str(value)) > MAX_FIELD_CHARS:
            return f"{name}_too_long"
        if detect_prompt_injection(str(value)):
            return "injection_in_field"
    if not fact.source_span:
        return "no_source_span"
    start, end = fact.source_span
    if not (0 <= start < end <= len(text)):
        return "span_out_of_range"
    span = text[start:end]
    if fact.excerpt.strip() and fact.excerpt.strip() not in span:
        return "excerpt_not_in_span"
    if detect_prompt_injection(span):
        return "span_is_injection"

    span_toks = set(_tokens(span))
    obj_toks = _tokens(fact.object)
    if not obj_toks or not any(t in span_toks for t in obj_toks):
        return "object_not_in_span"
    for raw in re.findall(r"[\w#+.]+", fact.object):
        t = _norm(raw).strip(".")
        if t and (any(c.isdigit() for c in t) or raw[:1].isupper()) and t not in span_toks:
            return "object_token_not_in_span"

    key = norm_entity(fact.subject)
    if key == "user" or fact.subject.strip().lower() in FIRST_PERSON:
        if not _FIRST_PERSON_CUE.search(span):
            return "subject_not_first_person"
    else:
        if key in _PRONOUNS:
            return "pronoun_subject"
        subj_toks = [t for t in _tokens(fact.subject) if t not in {"the", "a", "an", "project", "team", "company"}]
        chunk_toks = set(_tokens(text))
        if not subj_toks or not all(t in chunk_toks for t in subj_toks):
            return "subject_not_in_text"

    if not _PREDICATE_OK.match(fact.predicate.lower()):
        return "bad_predicate"
    if strict and not predicate_cue_present(fact.predicate, span):
        return "predicate_cue_missing"
    if fact.polarity == "affirmed" and _NEGATION_CUE.search(span):
        return "negation_dropped"
    if fact.polarity == "negated" and not _NEGATION_CUE.search(span):
        return "negation_invented"
    return None
