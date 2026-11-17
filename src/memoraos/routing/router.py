"""Adaptive Memory Routing Engine (AMRE): deterministic query analysis and strategy selection."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from ..config import Settings
from ..ingestion.dates import TimeRef, parse_time_reference
from ..models import RoutePlan
from ..providers.base import ChatProvider
from ..util import STOPWORDS, content_terms, stem, tokenize

STRATEGY_COST: dict[str, float] = {
    "exact": 1, "bm25": 2, "vector": 3, "temporal": 3, "episodic": 4, "procedural": 4, "hybrid": 5, "fusion": 5, "graph": 6, "latent": 7,
    "multistage": 10,
}
CATEGORIES = ["exact_fact", "temporal", "multi_hop", "procedural", "episodic", "summarization", "semantic"]

_R = lambda p: re.compile(p, re.I)  # noqa: E731
_EXACT = _R(r"\b(exact|exactly|precise|precisely|current|currently|right now|what(?:'s| is| are)|who(?:'s| is)|which|how much|how many|what version)\b")
_TEMPORAL = _R(
    r"\b(when|history|historical|previous|previously|formerly|used to|over the (?:last|past)|"
    r"(?:last|past) \w+ years?|timeline|changed?|as of|at the time|back in|ago|(?:19|20)\d{2})\b"
)
# "before/after/since/until/earlier" are ordinary words in prose questions ("...before it is stored"); on their own they
# only weakly suggest a time question. They count fully when a time reference is parsed or a stored fact slot matches.
_WEAK_TEMPORAL = _R(r"\b(before|after|since|until|earlier)\b")
_HISTORY = _R(r"\b(history|historical|timeline|over time|changed|all (?:the )?(?:values|versions|salaries)|every)\b")
_PREVIOUS = _R(r"\b(previous|previously|formerly|used to|before (?:it|that|this) changed|prior|earlier value|old)\b")
_MULTI_HOP = _R(r"\b(related|relationship|relate|connect(?:ed|ion)?|linked|link between|between|path|depends? on|dependency|through|via|indirectly|who .+ (?:that|which))\b")
_PERSONAL = _R(r"\b(my|mine|i|me|i'm|i've|we|our)\b")
_PROCEDURAL = _R(r"\b(how (?:do|to|can|should|would)|steps?|procedure|process for|runbook|workflow|troubleshoot|fix|set ?up|install|configure|checklist|deploy(?:ment)? process)\b")
_EPISODIC = _R(r"\b(what happened|did (?:i|we)|have (?:i|we)|discuss(?:ed)?|talk(?:ed)?|conversation|last time|worked on|decided|failed|incident|meeting|projects? .{0,30}(?:worked|done|built))\b")
_SUMMARY = _R(r"\b(summari[sz]e|summary|overview|overall|main themes?|key points|across all|everything about|all (?:the )?(?:papers|documents|notes|memories))\b")
_CODE_LIKE = re.compile(r"`[^`]+`|\"[^\"]+\"|\b[A-Z]{2,}-?\d+\b|\b\w+_\w+\b|\b[a-z]+[A-Z]\w+\b|0x[0-9a-fA-F]+|\bE\d{3,}\b")
_CAPS = re.compile(r"\b[A-Z][A-Za-z0-9.#+\-]+(?:\s+[A-Z][A-Za-z0-9.#+\-]+)*")
_FIRST_WORD_STOP = {"what", "which", "who", "when", "where", "why", "how", "is", "are", "do", "does", "did", "tell", "show", "list", "give", "the", "a", "an", "i", "my", "we", "in", "on", "summarize", "explain", "describe"}


@dataclass
class QueryFeatures:
    text: str
    terms: list[str]
    exact_cue: bool
    temporal_cue: bool
    history_ref: bool
    previous_ref: bool
    multi_hop_cue: bool
    personal: bool
    procedural_cue: bool
    episodic_cue: bool
    summary_cue: bool
    code_like: bool
    capitalized_entities: int
    word_count: int
    time_ref: TimeRef | None = field(default=None)
    entity_terms: list[str] = field(default_factory=list)
    head_term: str | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["time_ref"] = asdict(self.time_ref) if self.time_ref else None
        d.pop("text")
        return d


TIME_FILLER = frozenset(
    "last past recent recently ago year years month months week weeks day days over ever during within since until before after "
    "one two three four five six seven eight nine ten twelve earlier later".split()
)


def analyze_query(query: str, now=None) -> QueryFeatures:
    caps = [m.group(0) for m in _CAPS.finditer(query) if m.group(0).split()[0].lower() not in _FIRST_WORD_STOP]
    tref = parse_time_reference(query, now)
    cleaned = query.replace(tref.text, " ") if tref else query
    terms = [t for t in content_terms(cleaned) if t not in TIME_FILLER and t not in {stem(w) for w in TIME_FILLER}]
    words = query.split()
    return QueryFeatures(
        text=query,
        terms=terms,
        exact_cue=bool(_EXACT.search(query)),
        temporal_cue=bool(_TEMPORAL.search(query)) or tref is not None or bool(_EPISODIC.search(query) and _WEAK_TEMPORAL.search(query)),
        history_ref=bool(_HISTORY.search(query)),
        previous_ref=bool(_PREVIOUS.search(query)),
        multi_hop_cue=bool(_MULTI_HOP.search(query)),
        personal=bool(_PERSONAL.search(query)),
        procedural_cue=bool(_PROCEDURAL.search(query)),
        episodic_cue=bool(_EPISODIC.search(query)),
        summary_cue=bool(_SUMMARY.search(query)),
        code_like=bool(_CODE_LIKE.search(query)),
        capitalized_entities=len(caps),
        word_count=len(words),
        time_ref=tref,
        entity_terms=sorted({stem(w.lower().strip(".-")) for c in caps for w in c.split()}),
        head_term=_head_term(cleaned, terms, caps),
    )


def _head_term(text: str, terms: list[str], caps: list[str]) -> str | None:
    """The attribute a question asks about, approximated as its last content word that is neither a
    named entity nor a verb-like word (-ing). Evidence must mention it before an answer is accepted."""
    cap_words = {w.lower() for c in caps for w in c.split()}
    allowed = set(terms)
    for tok in reversed(tokenize(text)):
        if tok in STOPWORDS or tok in cap_words or tok.endswith("ing"):
            continue
        s = stem(tok)
        if s in allowed:
            return s
    return None


@dataclass
class RouterHints:
    """Cheap facts about the store that sharpen routing. Supplied by the engine."""

    slot_match: bool = False
    graph_entities: int = 0
    procedural_memories: bool = False
    latent_available: bool = False
    fusion_applicable: bool = False  # the question names a chain: anchor -> relation -> typed answer


def category_scores(f: QueryFeatures, h: RouterHints) -> dict[str, float]:
    short = f.word_count <= 12
    s = {
        "exact_fact": 0.15 * f.exact_cue + 0.6 * h.slot_match + 0.1 * (f.personal and h.slot_match) + 0.1 * f.code_like + 0.05 * short - 0.3 * f.multi_hop_cue,
        "temporal": 0.5 * f.temporal_cue + 0.2 * (f.time_ref is not None) + 0.2 * (f.history_ref or f.previous_ref) + 0.1 * h.slot_match + 0.15 * (h.slot_match and (f.history_ref or f.previous_ref or f.time_ref is not None)),
        "multi_hop": 0.55 * f.multi_hop_cue + 0.3 * (f.capitalized_entities >= 2 and f.multi_hop_cue) + 0.1 * (h.graph_entities >= 2),
        "procedural": 0.7 * f.procedural_cue + 0.15 * h.procedural_memories * f.procedural_cue,
        "episodic": 0.55 * f.episodic_cue + 0.15 * f.personal * f.episodic_cue + 0.15 * f.temporal_cue * f.episodic_cue,
        "summarization": 0.8 * f.summary_cue + 0.1 * (f.word_count > 8) * f.summary_cue,
    }
    s["semantic"] = 0.3 + (0.2 if max(s.values()) < 0.3 else 0.0)
    return {k: round(max(0.0, min(1.0, v)), 4) for k, v in s.items()}


# Strategy to run for each category, then fallbacks in order.
_CATEGORY_PLAN: dict[str, tuple[str, list[str]]] = {
    "exact_fact": ("exact", ["hybrid"]),
    "temporal": ("temporal", ["episodic", "hybrid"]),
    "multi_hop": ("graph", ["hybrid"]),
    "procedural": ("procedural", ["hybrid"]),
    "episodic": ("episodic", ["temporal", "hybrid"]),
    "summarization": ("multistage", ["hybrid"]),
    "semantic": ("hybrid", ["vector"]),
}


class AdaptiveRouter:
    def __init__(
        self,
        settings: Settings,
        *,
        classifier: ChatProvider | None = None,
        learned_policy: Callable[[str, str], str | None] | None = None,
    ):
        self.settings = settings
        self.classifier = classifier
        self.learned_policy = learned_policy

    def route(self, query: str, hints: RouterHints | None = None, *, now=None, allow_strategies: set[str] | None = None) -> RoutePlan:
        hints = hints or RouterHints()
        f = analyze_query(query, now)
        cats = category_scores(f, hints)
        ranked = sorted(cats.items(), key=lambda kv: (-kv[1], CATEGORIES.index(kv[0])))
        top_cat, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = round(min(1.0, top + (top - second)), 4)
        if top_cat == "semantic":
            confidence = min(confidence, 0.3)  # no routing cue fired: the default category is a weak signal
        reasons = [f"category '{top_cat}' scored {top:.2f} (next {ranked[1][0]} {second:.2f})"]

        # strategy scores: category evidence plus generic retrievers
        strat = {
            "exact": cats["exact_fact"] if hints.slot_match else 0.0,
            "temporal": cats["temporal"] if hints.slot_match or f.temporal_cue else 0.0,
            "graph": cats["multi_hop"] if hints.graph_entities else cats["multi_hop"] * 0.5,
            "procedural": cats["procedural"],
            "episodic": cats["episodic"],
            "multistage": cats["summarization"],
            "latent": 0.5 * cats["summarization"] if hints.latent_available else 0.0,
            "hybrid": 0.4,
            "bm25": 0.3 + (0.35 if f.code_like else 0.0),
            "vector": 0.2,
            "fusion": 0.95 if hints.fusion_applicable else 0.0,
        }
        if allow_strategies is not None:
            strat = {k: v for k, v in strat.items() if k in allow_strategies}
        best = max(strat.values())
        near = [k for k, v in strat.items() if v >= best - self.settings.cost_tolerance and v > 0]
        primary = min(near, key=lambda k: (STRATEGY_COST[k], -strat[k]))
        if primary != max(strat, key=strat.get):  # type: ignore[arg-type]
            reasons.append(f"cost-aware: chose cheaper '{primary}' within {self.settings.cost_tolerance} of the top score")
        default_primary, default_fallbacks = _CATEGORY_PLAN[top_cat]
        if default_primary in strat and strat[default_primary] >= strat[primary] - 1e-9 and top_cat != "semantic":
            primary = default_primary
        if f.code_like and top_cat == "semantic":
            primary = "bm25" if "bm25" in strat else primary
            reasons.append("identifier/quoted-literal detected: lexical retrieval first")
        fused_first = False
        if hints.fusion_applicable and "fusion" in strat:
            primary = "fusion"
            fused_first = True
            reasons.append("question names a chain (anchor -> relation -> typed answer): evidence fusion first")

        learned = False
        if self.learned_policy:
            alt = self.learned_policy(top_cat, primary)
            if alt and alt != primary and (allow_strategies is None or alt in allow_strategies):
                reasons.append(f"learned policy overrides '{primary}' with '{alt}' (guarded by accuracy)")
                primary, learned = alt, True

        fallbacks = [s for s in default_fallbacks if s != primary]
        if fused_first and default_primary != primary and default_primary not in fallbacks:
            fallbacks.insert(0, default_primary)  # if the chain cannot be proven, the ordinary strategy still gets its turn
        for s in ("hybrid", "vector"):
            if s not in fallbacks and s != primary:
                fallbacks.append(s)
        if confidence < self.settings.low_route_confidence:
            reasons.append(f"low routing confidence ({confidence:.2f}); hybrid retrieval promoted as first fallback")
            fallbacks = ["hybrid"] + [s for s in fallbacks if s != "hybrid"]
            if self.classifier and not learned:
                alt_cat = self._model_classify(query)
                if alt_cat and alt_cat != top_cat:
                    dp, df = _CATEGORY_PLAN[alt_cat]
                    reasons.append(f"model classifier suggested '{alt_cat}'")
                    top_cat, primary = alt_cat, dp
                    fallbacks = [s for s in df if s != dp] + [s for s in ("hybrid", "vector") if s != dp and s not in df]
        if allow_strategies is not None:
            fallbacks = [s for s in fallbacks if s in allow_strategies]
        stages = [primary] + [s for s in fallbacks if s != primary]
        return RoutePlan(
            category=top_cat, primary=primary, stages=stages, fallbacks=stages[1:], scores={**{f"cat:{k}": v for k, v in cats.items()}, **{k: round(v, 4) for k, v in strat.items()}},
            features=f.as_dict() | {"hints": asdict(hints)}, reasons=reasons, route_confidence=confidence,
            estimated_cost=float(STRATEGY_COST[primary]), learned_override=learned,
        )

    def _model_classify(self, query: str) -> str | None:
        assert self.classifier is not None
        prompt = (
            "Classify the user's question about stored memories into exactly one label from: "
            + ", ".join(CATEGORIES) + '. Reply with JSON like {"category": "<label>"} and nothing else.\nQuestion: ' + json.dumps(query)
        )
        try:
            text = self.classifier.complete([{"role": "user", "content": prompt}], max_tokens=30).text
            label = json.loads(text[text.index("{") : text.rindex("}") + 1]).get("category")
        except Exception:  # noqa: BLE001 - classification is best-effort and must never break routing
            return None
        return label if label in CATEGORIES else None
