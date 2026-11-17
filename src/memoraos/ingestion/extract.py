"""Deterministic rule-based fact and entity extraction.

This is intentionally simple and inspectable. It covers common declarative English patterns and is
replaceable through the ``EntityExtractor`` provider interface or by passing explicit ``facts=``.
Its limits are documented in docs/MEMORY_DESIGN.md and measured in the benchmark suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..providers.local import split_sentences
from ..security import detect_prompt_injection
from ..util import STOPWORDS
from .dates import extract_dates
from .lexicon import RELATIONAL_PREDICATES

FIRST_PERSON = {"i", "my", "me", "we", "our", "us", "myself", "i'm", "i've", "user", "the user"}
_PRONOUNS = {"it", "this", "that", "they", "he", "she", "there", "these", "those", "which", "who", "what", "here", "its", "their", "his", "her"}
_GENERIC_PREFIX = {"project", "team", "company", "service", "app", "application", "repo", "repository", "product", "module", "the", "our", "my", "a", "an"}
_ADVERBS = re.compile(r"\b(?:currently|now|still|also|recently|actually|finally|just|officially)\b\s*", re.I)

_SYNONYM_PREDICATES = {
    "pay": "salary", "compensation": "salary", "ctc": "salary", "income": "salary", "package": "salary",
    "salary": "salary", "earnings": "salary", "wage": "salary", "db": "database", "city": "location",
}


def norm_entity(name: str) -> str:
    n = name.strip().strip("\"'`").lower()
    n = re.sub(r"(?:'s|’s)$", "", n)
    n = re.sub(r"[^\w\s.#+\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip(" .")
    if n in FIRST_PERSON:
        return "user"
    words = n.split()
    while len(words) > 1 and words[0] in _GENERIC_PREFIX:
        words = words[1:]
    return " ".join(words)


def norm_predicate(p: str) -> str:
    p = re.sub(r"\s+", " ", p.strip().lower())
    p = re.sub(r"^(?:the|a|an|current|new|our|my)\s+", "", p)
    words = p.split()
    if len(words) == 1 and words[0] in _SYNONYM_PREDICATES:
        return _SYNONYM_PREDICATES[words[0]]
    if words and words[-1] in _SYNONYM_PREDICATES and len(words) <= 2:
        return _SYNONYM_PREDICATES[words[-1]]
    return p


def norm_object(obj: str) -> str:
    o = re.sub(r"\s+", " ", obj.strip().lower().strip("\"'`.,;"))
    o = re.sub(r"^(?:a|an|the)\s+", "", o)
    return o


@dataclass
class ExtractedFact:
    subject: str
    predicate: str
    object: str
    valid_from: str | None
    valid_until: str | None
    precision: str | None
    confidence: float
    excerpt: str


# (regex for the verb phrase, canonical predicate, subject/object swapped?)
_VERB_RULES: list[tuple[str, str, bool]] = [
    (r"(?:is|are|was|were) (?:led|managed|headed|owned|maintained|run) by", "leads", True),
    (r"(?:is|are|was|were) (?:employed (?:by|at)|working (?:at|for))", "works_at", False),
    (r"(?:works?|worked) (?:at|for)", "works_at", False),
    (r"(?:joined|joins)", "works_at", False),
    (r"(?:lives?|lived|resides?|is based|are based|was based) in", "lives_in", False),
    (r"(?:moved|relocated|relocates) to", "lives_in", False),
    (r"(?:is|are|was|were) (?:hosted|deployed) (?:in|on|at)", "hosted_in", False),
    (r"(?:is|are) (?:built|written) (?:with|in|using)", "uses", False),
    (r"(?:runs|ran) on", "uses", False),
    (r"(?:uses?|used|is using|are using|adopted|adopts|migrated to|migrates to)", "uses", False),
    (r"(?:prefers?|preferred|likes?|loves?)", "prefers", False),
    (r"(?:is|are) (?:building|developing|creating)", "building", False),
    (r"(?:builds?|built|develops?|developed)", "building", False),
    (r"(?:leads?|led|manages?|managed|owns?|owned|maintains?|maintained)", "leads", False),
    (r"(?:depends|relies|rely|depend) on", "depends_on", False),
    (r"(?:requires?|required)", "depends_on", False),
    (r"reports to", "reports_to", False),
    (r"(?:is|are|was|were) (?:part of|a part of|a component of)", "part_of", False),
    (r"(?:belongs to)", "part_of", False),
    (r"(?:integrates|connects) (?:with|to)", "connected_to", False),
    (r"(?:earns?|earned)", "salary", False),
]
_VERB_RE = [(re.compile(rf"\b{p}\b", re.I), pred, rev) for p, pred, rev in _VERB_RULES]

_POSSESSIVE = re.compile(
    r"^(?P<s>.+?)(?:'s|’s) (?P<p>[A-Za-z][\w\- ]{1,40}?) (?:is|was|are|were|will be) (?P<o>.+)$", re.I
)
_OF_FORM = re.compile(
    r"^(?:the )?(?P<p>[A-Za-z][\w\- ]{1,40}?) of (?P<s>.+?) (?:is|was|are|were|will be) (?P<o>.+)$", re.I
)
_MY_FORM = re.compile(r"^(?:my|our) (?P<p>[A-Za-z][\w\- ]{1,40}?) (?:is|was|are|were) (?P<o>.+)$", re.I)
_COPULA = re.compile(r"^(?P<s>.+?) (?:is|was|are|were) (?:a|an|the) (?P<o>.+)$", re.I)

_MULTI_VALUED_SPLIT = {"uses", "depends_on", "prefers", "building"}


def _words(s: str) -> int:
    return len(s.split())


def _clean_object(obj: str, predicate: str) -> str:
    o = obj.strip().strip("\"'`").rstrip(".,;!")
    o = re.sub(r"^(?:a|an|the)\s+", "", o, flags=re.I) if predicate not in {"is"} else o
    return o.strip()


def _split_objects(obj: str, predicate: str) -> list[str]:
    if predicate not in _MULTI_VALUED_SPLIT:
        return [obj]
    parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", obj) if p.strip()]
    if 1 < len(parts) <= 6 and all(_words(p) <= 4 for p in parts):
        return parts
    return [obj]


def _subject_ok(subject: str) -> bool:
    s = subject.strip().lower()
    if not s or _words(s) > 6:
        return False
    first = s.split()[0]
    if first in _PRONOUNS and s not in FIRST_PERSON:
        return False
    return not re.match(r"^(?:if|when|while|because|although|since|after|before|but|and|so)\b", s)


def extract_facts(text: str, *, default_subject: str = "user") -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    for sentence in split_sentences(text):
        if sentence.endswith("?") or detect_prompt_injection(sentence):
            continue
        facts.extend(_extract_sentence(sentence, default_subject))
    return facts


def _extract_sentence(sentence: str, default_subject: str) -> list[ExtractedFact]:
    dates = extract_dates(sentence)
    clause = _ADVERBS.sub("", dates.cleaned).strip().rstrip(".!")
    if not clause or _words(clause) < 3:
        return []
    clause = re.sub(r"^(?:and|but|so|also)\s+", "", clause, flags=re.I)

    def make(s: str, p: str, o: str, conf: float) -> list[ExtractedFact]:
        p = norm_predicate(p)
        out = []
        o = _clean_object(o, p)
        if not o or _words(o) > 14 or not _subject_ok(s):
            return []
        for part in _split_objects(o, p):
            out.append(
                ExtractedFact(
                    subject=s.strip().strip("\"'`"),
                    predicate=p,
                    object=part,
                    valid_from=dates.valid_from,
                    valid_until=dates.valid_until,
                    precision=dates.precision,
                    confidence=round(conf - (0.1 if _words(part) > 8 else 0.0), 2),
                    excerpt=sentence,
                )
            )
        return out

    m = _MY_FORM.match(clause)
    if m:
        return make("I", m.group("p"), m.group("o"), 0.9)
    m = _POSSESSIVE.match(clause)
    if m:
        return make(m.group("s"), m.group("p"), m.group("o"), 0.9)
    m = _OF_FORM.match(clause)
    if m:
        return make(m.group("s"), m.group("p"), m.group("o"), 0.9)

    best: tuple[int, int, re.Match[str], str, bool] | None = None
    for rx, pred, rev in _VERB_RE:
        vm = rx.search(clause)
        if vm and (best is None or vm.start() < best[0] or (vm.start() == best[0] and vm.end() - vm.start() > best[1])):
            best = (vm.start(), vm.end() - vm.start(), vm, pred, rev)
    if best:
        _, _, vm, pred, rev = best
        subj, obj = clause[: vm.start()].strip(), clause[vm.end() :].strip()
        if subj.lower() in {"i", "we"} and not subj:
            subj = default_subject
        if rev:
            subj, obj = obj, subj
        return make(subj, pred, obj, 0.8)

    m = _COPULA.match(clause)
    if m:
        return make(m.group("s"), "is", m.group("o"), 0.5)
    return []


_CAP_SEQ = re.compile(r"\b[A-Z][A-Za-z0-9.#+\-]*(?:\s+[A-Z][A-Za-z0-9.#+\-]*)*")
_NOISE_ENTITIES = {"lpa", "usd", "inr", "eur", "gbp", "ok", "yes", "no", "mr", "mrs", "ms", "dr"}


def extract_entities(text: str, facts: list[ExtractedFact] | None = None) -> dict[str, str]:
    """Return {entity_key: display_name} for capitalised names plus fact subjects/objects."""
    found: dict[str, str] = {}
    for sentence in split_sentences(text):
        for m in _CAP_SEQ.finditer(sentence):
            words = m.group(0).split()
            while words and words[0].lower() in STOPWORDS:
                words = words[1:]
            if not words:
                continue
            name = " ".join(words).strip(".-")
            key = norm_entity(name)
            if len(key) < 2 or key in _NOISE_ENTITIES or key in STOPWORDS or key == "user":
                continue
            found.setdefault(key, name)
    for f in facts or []:
        skey = norm_entity(f.subject)
        if skey and skey != "user" and skey not in STOPWORDS:
            found.setdefault(skey, f.subject)
        if f.predicate in RELATIONAL_PREDICATES and _words(f.object) <= 4:
            okey = norm_entity(f.object)
            if okey and okey not in STOPWORDS:
                found.setdefault(okey, f.object)
    return found
