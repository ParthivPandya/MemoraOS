"""Deterministic synthetic datasets for the Memory Benchmark Lab.

Everything is generated from a seed with ``random.Random``; no network, no external data. The
generators were written to exercise *specific, documented capabilities* (see docs/BENCHMARK_METHODOLOGY.md).
They are synthetic and authored by the MemoraOS project, so results must not be read as a claim about
real-world conversational data (use LoCoMo / LongMemEval for that; see the roadmap).
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)

FIRST = """Priya Rohan Ananya Vikram Meera Arjun Kavya Rahul Neha Sanjay Isha Dev Tara Kabir Anika Rohit Diya Karan
Sana Nikhil Pooja Aditya Riya Manish Leela Harsh Mira Yash Zoya Ishaan Nisha Varun Tanvi Omar Sofia Liam Chloe
Mateo Hana Jonas Lena Felix Ingrid Marco Elif Tomas Alma Ravi Selin Dario Petra""".split()
CITIES = """Pune Mumbai Delhi Bengaluru Chennai Kolkata Jaipur Lucknow Indore Kochi Nagpur Surat Bhopal Patna Mysuru
Vadodara Nashik Goa Shimla Dehradun Ranchi Raipur Guwahati Madurai Agra Amritsar Udaipur Jodhpur Kanpur Rajkot""".split()
COMPANIES = """Contoso Fabrikam Globex Initech Umbrella Hooli Vandelay Stark Wayne Wonka Cyberdyne Tyrell Aperture Soylent
Massive Oscorp Gringotts Dunder Pied Nakatomi Monarch Rekall Wernham Bluth Prestige Sterling Krusty Gekko Acme""".split()
LANGS = "Python Rust Go Kotlin Swift Haskell Elixir Scala Ruby Lua Julia Zig Clojure Erlang Dart".split()
EDITORS = "Neovim Emacs Helix Sublime Kakoune Atom Zed Nano Micro Geany Kate Lapce Vim Xi Brackets".split()
WORDS = """Zephyr Orion Basalt Cobalt Quartz Ember Nimbus Falcon Lotus Mistral Pinnacle Vortex Tundra Borealis Cascade
Sierra Aurora Helix Onyx Prism Summit Meridian Aegis Beacon Cinder Drift Equinox Fjord Glacier Harbor Ivory Jasper
Kestrel Lagoon Marble Nebula Obsidian Pebble Quill Raven Saffron Thistle Umbra Velvet Willow Yarrow Zenith""".split()
DBS = "PostgreSQL MySQL MariaDB MongoDB Cassandra Redis DynamoDB CockroachDB Neo4j SQLite ClickHouse Elasticsearch Firebird".split()
STATES = """green amber red blue violet orange teal indigo crimson olive maroon cyan magenta lime coral navy khaki
lavender salmon turquoise plum ivory tan beige mint rose azure gold silver bronze copper""".split()
FILLER_TOPICS = """the quarterly planning cycle|the onboarding checklist|the office relocation|the vendor review|the training budget|the
holiday schedule|the security awareness session|the design guild meeting|the hiring pipeline|the data retention policy|the
cafeteria menu|the travel policy|the accessibility audit|the incident review template|the brand refresh""".split("|")


@dataclass
class Event:
    idx: int
    kind: str  # add | correct
    text: str
    user: str
    recorded_at: str
    effective_at: str | None = None
    source_type: str = "user_statement"
    target: int | None = None  # for kind == correct: idx of the event being corrected
    session: str | None = None


@dataclass
class Question:
    qid: str
    scenario: str
    text: str
    user: str
    gold: list[str] = field(default_factory=list)
    wrong: list[str] = field(default_factory=list)
    relevant: list[int] = field(default_factory=list)
    answerable: bool = True
    as_of: str | None = None
    kind: str = "answer"  # answer | conflict | update_no_conflict
    after_event: int | None = None  # ask only after this many events (degradation curve)
    tag: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    events: list[Event]
    questions: list[Question]
    capability: str = ""
    restart: bool = False
    consolidate: bool = False


def _ts(day: float) -> str:
    return (BASE + timedelta(days=day)).isoformat()


class _Pool:
    """Draw unique items from a pool, extending with numbered variants if exhausted."""

    def __init__(self, rng: random.Random, items: list[str]):
        self.rng, self.items, self.used, self.n = rng, list(items), set(), 0

    def take(self) -> str:
        avail = [i for i in self.items if i not in self.used]
        if not avail:
            self.n += 1
            self.items = [f"{i}{self.n}" for i in self.items]
            avail = list(self.items)
        pick = self.rng.choice(sorted(avail))
        self.used.add(pick)
        return pick


def _sal(n: int) -> str:
    return f"₹{n} LPA"


def single_fact(rng: random.Random, scale: float) -> Scenario:
    n = max(8, int(40 * scale))
    names = _Pool(rng, FIRST)
    people = [names.take() for _ in range(n)]
    ev: list[Event] = []
    qs: list[Question] = []
    facts = []
    for p in people:
        city, comp, lang = rng.choice(CITIES), rng.choice(COMPANIES), rng.choice(LANGS)
        facts.append((p, city, comp, lang))
        for text in (f"{p} lives in {city}.", f"{p} works at {comp}.", f"{p}'s favorite language is {lang}."):
            ev.append(Event(len(ev), "add", text, "u1", _ts(len(ev))))
    rng.shuffle(facts)
    for i, (p, city, comp, lang) in enumerate(facts[: max(6, n // 2)]):
        base = next(e.idx for e in ev if e.text.startswith(f"{p} lives"))
        kind = i % 3
        if kind == 0:
            qs.append(Question(f"sf{i}", "single_fact_recall", f"Where does {p} live?", "u1", [city], [], [base]))
        elif kind == 1:
            qs.append(Question(f"sf{i}", "single_fact_recall", f"Where does {p} work?", "u1", [comp], [], [base + 1]))
        else:
            qs.append(Question(f"sf{i}", "single_fact_recall", f"What is {p}'s favorite language?", "u1", [lang], [], [base + 2]))
    return Scenario("single_fact_recall", "One fact per person among many similar facts.", ev, qs, "exact fact lookup")


def multi_document(rng: random.Random, scale: float) -> Scenario:
    n = max(5, int(12 * scale))
    projects, techs = _Pool(rng, WORDS), _Pool(rng, DBS + LANGS + EDITORS)
    groups = []
    docs: list[str] = []
    for _ in range(n):
        proj = f"Project {projects.take()}"
        ts_ = [techs.take() for _ in range(3)]
        groups.append((proj, ts_))
        docs.extend(f"{proj} uses {t}." for t in ts_)
    rng.shuffle(docs)
    ev = [Event(i, "add", text, "u1", _ts(i), source_type="document") for i, text in enumerate(docs)]
    pos = {e.text: e.idx for e in ev}
    qs = [
        Question(f"md{i}", "multi_document_recall", f"What technologies does {proj} use?", "u1", ts_, [], [pos[f"{proj} uses {t}."] for t in ts_])
        for i, (proj, ts_) in enumerate(groups)
    ]
    return Scenario("multi_document_recall", "Facts about one subject spread over three documents.", ev, qs, "multi-document aggregation")

def multi_hop(rng: random.Random, scale: float) -> Scenario:
    n = max(4, int(10 * scale))
    people, words = _Pool(rng, FIRST), _Pool(rng, WORDS)
    ev: list[Event] = []
    qs: list[Question] = []
    chains = []
    for _ in range(n):
        person = people.take()
        project, service, store, region = f"Project {words.take()}", f"{words.take()} Queue", f"{words.take()} DB", f"Region {words.take()}"
        texts = [f"{person} leads {project}.", f"{project} uses {service}.", f"{service} depends on {store}.", f"{store} is hosted in {region}."]
        chains.append((person, project, service, store, region, texts))
    order = [(ci, ti) for ci in range(n) for ti in range(4)]
    rng.shuffle(order)
    pos = {}
    for ci, ti in order:
        ev.append(Event(len(ev), "add", chains[ci][5][ti], "u1", _ts(len(ev)), source_type="document"))
        pos[(ci, ti)] = ev[-1].idx
    for ci, (person, project, service, store, region, _t) in enumerate(chains):
        qs.append(Question(f"mh{ci}", "multi_hop_reasoning", f"How is {person} connected to {region}?", "u1", [project, service, store], [], [pos[(ci, t)] for t in range(4)]))
    return Scenario("multi_hop_reasoning", "Four-hop chains: person -> project -> service -> datastore -> region.", ev, qs, "graph traversal")


def temporal(rng: random.Random, scale: float) -> Scenario:
    n = max(6, int(15 * scale))
    names = _Pool(rng, FIRST)
    ev: list[Event] = []
    qs: list[Question] = []
    for i in range(n):
        p = names.take()
        vals = sorted(rng.sample(range(10, 90), 3))
        years = [2023, 2024, 2025]
        order = list(range(3))
        rng.shuffle(order)  # learned out of chronological order
        idx_of = {}
        for k in order:
            ev.append(Event(len(ev), "add", f"{p}'s salary is {_sal(vals[k])} in {years[k]}.", "u1", _ts(len(ev))))
            idx_of[k] = ev[-1].idx
        wrong_all = [_sal(v) for v in vals]
        qs.append(Question(f"t{i}a", "temporal_reasoning", f"What is {p}'s current salary?", "u1", [_sal(vals[2])], [w for w in wrong_all if w != _sal(vals[2])], [idx_of[2]], tag="current"))
        y = rng.choice([0, 1])
        qs.append(Question(f"t{i}b", "temporal_reasoning", f"What was {p}'s salary in {years[y]}?", "u1", [_sal(vals[y])], [w for w in wrong_all if w != _sal(vals[y])], [idx_of[y]], tag="at_year"))
        qs.append(Question(f"t{i}c", "temporal_reasoning", f"What was {p}'s previous salary before it changed?", "u1", [_sal(vals[1])], [w for w in wrong_all if w != _sal(vals[1])], [idx_of[1]], tag="previous"))
    return Scenario("temporal_reasoning", "Salary histories ingested out of order; current, at-year and previous questions.", ev, qs, "bitemporal facts")


def historical(rng: random.Random, scale: float) -> Scenario:
    n = max(5, int(10 * scale))
    projects = _Pool(rng, WORDS)
    ev: list[Event] = []
    qs: list[Question] = []
    for i in range(n):
        proj = f"Project {projects.take()}"
        versions = rng.sample(DBS, 3)
        ids = []
        for v in versions:
            ev.append(Event(len(ev), "add", f"The database of {proj} is {v}.", "u1", _ts(len(ev) * 2)))
            ids.append(ev[-1].idx)
        at = [(BASE + timedelta(days=ev[j].idx * 2 + 1)).isoformat() for j in ids]
        qs.append(Question(f"h{i}a", "historical_reconstruction", f"Which database does {proj} use?", "u1", [versions[1]], [versions[0], versions[2]], [ids[1]], as_of=at[1], tag="as_of_middle"))
        qs.append(Question(f"h{i}b", "historical_reconstruction", f"Which database does {proj} use?", "u1", [versions[0]], [versions[1], versions[2]], [ids[0]], as_of=at[0], tag="as_of_first"))
        qs.append(Question(f"h{i}c", "historical_reconstruction", f"Which database does {proj} use?", "u1", [], [versions[0], versions[1], versions[2]], [], answerable=False, as_of=(BASE - timedelta(days=1)).isoformat(), tag="before_known"))
        qs.append(Question(f"h{i}d", "historical_reconstruction", f"Which database does {proj} use?", "u1", [versions[2]], [versions[0], versions[1]], [ids[2]], tag="now"))
    return Scenario("historical_reconstruction", "What did the system know on a given date? Includes dates before anything was known.", ev, qs, "time travel")


def contradiction(rng: random.Random, scale: float) -> Scenario:
    n = max(4, int(6 * scale))
    projects = _Pool(rng, WORDS)
    ev: list[Event] = []
    qs: list[Question] = []
    for i in range(n):  # version updates (not contradictions)
        proj = f"Project {projects.take()}"
        a, b = rng.sample(range(8, 20), 2)
        lo, hi = min(a, b), max(a, b)
        ev.append(Event(len(ev), "add", f"{proj} uses Angular {lo}.", "u1", _ts(len(ev)), source_type="document"))
        ev.append(Event(len(ev), "add", f"{proj} uses Angular {hi}.", "u1", _ts(len(ev)), source_type="document"))
        qs.append(Question(f"c{i}u", "contradiction_resolution", f"Which Angular version does {proj} use?", "u1", [f"Angular {hi}"], [f"Angular {lo}"], [ev[-1].idx], kind="update_no_conflict"))
    for i in range(n):  # genuine conflicts from two documents
        proj = f"Project {projects.take()}"
        x, y = rng.sample(DBS, 2)
        ev.append(Event(len(ev), "add", f"The database of {proj} is {x}.", "u1", _ts(len(ev)), source_type="document"))
        ev.append(Event(len(ev), "add", f"The database of {proj} is {y}.", "u1", _ts(len(ev)), source_type="document"))
        qs.append(Question(f"c{i}x", "contradiction_resolution", f"Which database does {proj} use?", "u1", [], [], [ev[-1].idx - 1, ev[-1].idx], kind="conflict"))
    return Scenario("contradiction_resolution", "Version updates (must resolve to the latest) and genuine conflicts (must be flagged).", ev, qs, "contradiction detection")


def personalization(rng: random.Random, scale: float) -> Scenario:
    n = max(4, int(8 * scale))
    names = _Pool(rng, FIRST)
    editors, cities, langs = _Pool(rng, EDITORS), _Pool(rng, CITIES), _Pool(rng, LANGS)
    ev: list[Event] = []
    qs: list[Question] = []
    users = []
    for _ in range(n):
        u = f"user_{names.take().lower()}"
        users.append((u, editors.take(), cities.take(), langs.take()))
    for u, ed, city, lang in users:
        for text in (f"I prefer {ed}.", f"I live in {city}.", f"My favorite language is {lang}."):
            ev.append(Event(len(ev), "add", text, u, _ts(len(ev))))
    for k, (u, ed, city, _lang) in enumerate(users):
        others_ed = [x[1] for x in users if x[0] != u]
        others_city = [x[2] for x in users if x[0] != u]
        first = next(e.idx for e in ev if e.user == u)
        qs.append(Question(f"p{k}a", "user_personalization", "What editor do I prefer?", u, [ed], others_ed, [first]))
        qs.append(Question(f"p{k}b", "user_personalization", "Where do I live?", u, [city], others_city, [first + 1]))
    return Scenario("user_personalization", "First-person facts for many users; questions use 'I' and 'my'.", ev, qs, "per-user memory and first-person resolution")


def long_conversation(rng: random.Random, scale: float) -> Scenario:
    n_chat = max(60, int(150 * scale))
    topics, food = FILLER_TOPICS, ["dal", "pasta", "salad", "biryani", "soup", "tacos", "ramen", "idli", "pizza", "curry"]
    items = ["milk", "printer paper", "batteries", "a gift card", "umbrella", "charger", "stamps", "tea", "notebooks", "light bulbs"]
    managers, cities, comps, eds = _Pool(rng, FIRST), _Pool(rng, CITIES), _Pool(rng, COMPANIES), _Pool(rng, EDITORS)
    mgr, city, comp, ed = managers.take(), cities.take(), comps.take(), eds.take()
    decoy_friend, decoy_city, decoy_mgr = managers.take(), cities.take(), managers.take()
    planted = [
        (f"I live in {city}.", "Where do I live?", city, [decoy_city]),
        (f"My manager is {mgr}.", "Who is my manager?", mgr, [decoy_mgr]),
        (f"I work at {comp}.", "Where do I work?", comp, []),
        (f"My favorite editor is {ed}.", "What is my favorite editor?", ed, []),
        (f"My friend {decoy_friend} lives in {decoy_city}.", None, None, []),
        (f"The manager of my friend {decoy_friend} is {decoy_mgr}.", None, None, []),
    ]
    slots = sorted(rng.sample(range(n_chat), len(planted)))
    ev: list[Event] = []
    qs: list[Question] = []
    pi = 0
    plant_idx: dict[int, int] = {}
    for i in range(n_chat):
        if pi < len(planted) and i == slots[pi]:
            ev.append(Event(len(ev), "add", planted[pi][0], "u1", _ts(len(ev) / 4), source_type="conversation", session=f"s{i // 40}"))
            plant_idx[pi] = ev[-1].idx
            pi += 1
            continue
        kind = rng.randrange(3)
        text = (f"We talked about {rng.choice(topics)} today.", f"I had {rng.choice(food)} for lunch.", f"Remember to buy {rng.choice(items)}.")[kind]
        ev.append(Event(len(ev), "add", text, "u1", _ts(len(ev) / 4), source_type="conversation", session=f"s{i // 40}"))
    for k, (_t, q, gold, wrong) in enumerate(planted):
        if q:
            qs.append(Question(f"lc{k}", "long_conversation", q, "u1", [gold], wrong, [plant_idx[k]]))
    return Scenario("long_conversation", "Facts planted in a long chat, with near-miss decoys about a friend.", ev, qs, "needle in conversation history")


def long_document(rng: random.Random, scale: float) -> Scenario:
    n = max(4, int(6 * scale))
    services = _Pool(rng, WORDS)
    ev: list[Event] = []
    qs: list[Question] = []
    for d in range(n):
        svc = f"{services.take()} Gateway"
        other = [f"{services.take()} Gateway" for _ in range(3)]
        minutes = rng.randrange(5, 95)
        paras = []
        needle_at = rng.randrange(4, 10)
        for p in range(12):
            if p == needle_at:
                paras.append(f"Operational note. The rollback window for {svc} is {minutes} minutes.")
            else:
                topic = rng.choice(FILLER_TOPICS)
                s = rng.choice(other + [svc])
                paras.append(f"Section {p + 1}. The team reviewed {topic} with the owners of {s}. {s} is monitored by the platform group and reviewed every quarter. " + " ".join(f"Action item {j}: follow up on {rng.choice(FILLER_TOPICS)}." for j in range(5)))
        ev.append(Event(len(ev), "add", "\n\n".join(paras), "u1", _ts(len(ev)), source_type="document"))
        qs.append(Question(f"ld{d}", "long_document_retrieval", f"What is the rollback window for {svc}?", "u1", [f"{minutes} minutes"], [], [ev[-1].idx]))
    return Scenario("long_document_retrieval", "A single needle sentence inside ~10k-character documents full of near-duplicate filler.", ev, qs, "chunking and passage retrieval")


def update_correction(rng: random.Random, scale: float) -> Scenario:
    n = max(6, int(12 * scale))
    projects, people = _Pool(rng, WORDS), _Pool(rng, FIRST)
    ev: list[Event] = []
    qs: list[Question] = []
    for i in range(n):
        proj, old, new = f"Project {projects.take()}", people.take(), people.take()
        ev.append(Event(len(ev), "add", f"The owner of {proj} is {old}.", "u1", _ts(len(ev))))
        first = ev[-1].idx
        if i % 2 == 0:  # explicit correction of the stored memory
            ev.append(Event(len(ev), "correct", f"The owner of {proj} is {new}.", "u1", _ts(len(ev)), target=first))
            rel = [first]
        else:  # restated later, original left in place
            ev.append(Event(len(ev), "add", f"The owner of {proj} is {new}.", "u1", _ts(len(ev))))
            rel = [ev[-1].idx]
        qs.append(Question(f"u{i}", "memory_update_correction", f"Who is the owner of {proj}?", "u1", [new], [old], rel, tag="correct" if i % 2 == 0 else "restate"))
    return Scenario("memory_update_correction", "Explicit corrections and later restatements of changed facts.", ev, qs, "update handling")


def consolidation(rng: random.Random, scale: float) -> Scenario:
    n = max(5, int(8 * scale))
    names, cities = _Pool(rng, FIRST), _Pool(rng, CITIES)
    ev: list[Event] = []
    qs: list[Question] = []
    for i in range(n):
        p, c = names.take(), cities.take()
        variants = [f"{p} lives in {c}.", f"{p} currently lives in {c}.", f"{p} lives in {c}, as mentioned before.", f"{p} lives in {c}."]
        idxs = []
        for v in variants:
            ev.append(Event(len(ev), "add", v, "u1", _ts(len(ev)), source_type="conversation"))
            idxs.append(ev[-1].idx)
        qs.append(Question(f"co{i}", "memory_consolidation", f"Where does {p} live?", "u1", [c], [], idxs))
    for _ in range(3):  # recurring topic notes that consolidation can summarise
        topic = f"{rng.choice(WORDS)} architecture"
        for j in range(5):
            ev.append(Event(len(ev), "add", f"Meeting note {j}: we reviewed the {topic} and its rollout plan.", "u1", _ts(len(ev)), source_type="conversation"))
    return Scenario("memory_consolidation", "Duplicated and paraphrased restatements plus recurring topic notes; consolidation must not lose evidence or accuracy.", ev, qs, "consolidation safety", consolidate=True)


def evidence_attribution(rng: random.Random, scale: float) -> Scenario:
    n = max(6, int(15 * scale))
    names, cities, comps = _Pool(rng, FIRST), _Pool(rng, CITIES), _Pool(rng, COMPANIES)
    ev: list[Event] = []
    qs: list[Question] = []
    for i in range(n):
        p, q_, c, c2 = names.take(), names.take(), cities.take(), comps.take()
        text = f"Meeting notes {i}. {q_} works at {c2}. The cafeteria opens at 9 today. {p} lives in {c}. Parking is limited on Fridays."
        ev.append(Event(len(ev), "add", text, "u1", _ts(len(ev)), source_type="document"))
        qs.append(Question(f"ea{i}", "evidence_attribution", f"Where does {p} live?", "u1", [c], [], [ev[-1].idx], tag="sentence_level"))
    return Scenario("evidence_attribution", "Answer sits in one sentence of a multi-sentence note; evidence must point at the right note and sentence.", ev, qs, "source attribution")


def degradation(rng: random.Random, scale: float) -> Scenario:
    n_updates = 40 if scale >= 1 else 20
    services = _Pool(rng, WORDS)
    svcs = [f"{services.take()} Service" for _ in range(3)]
    ev: list[Event] = []
    qs: list[Question] = []
    latest = {s: None for s in svcs}
    checkpoints = {1, 5, 10, 20, n_updates}
    seq = {s: rng.sample(STATES, len(STATES)) for s in svcs}
    for k in range(n_updates):
        for s in svcs:
            state = seq[s][k % len(STATES)] + ("" if k < len(STATES) else str(k))
            ev.append(Event(len(ev), "add", f"The status of {s} is {state}.", "u1", _ts(len(ev) / 3)))
            latest[s] = (state, ev[-1].idx)
        if (k + 1) in checkpoints:
            for s in svcs:
                prior = [seq[s][j % len(STATES)] + ("" if j < len(STATES) else str(j)) for j in range(k)]
                qs.append(Question(f"dg{k + 1}{s[:3]}", "degradation_after_updates", f"What is the status of {s}?", "u1", [latest[s][0]], prior[-3:], [latest[s][1]], after_event=len(ev), tag=f"after_{k + 1}_updates"))
    return Scenario("degradation_after_updates", "The same facts overwritten many times; accuracy is measured after 1, 5, 10, 20, ... updates.", ev, qs, "stability under repeated updates")


def unsupported(rng: random.Random, scale: float) -> Scenario:
    base = single_fact(rng, scale * 0.5)
    ev = base.events
    names = sorted({e.text.split()[0].rstrip("'s") for e in ev})
    qs = list(base.questions[: max(6, len(base.questions) // 2)])
    for q in qs:
        q.scenario = "unsupported_answers"
    attrs = ["blood group", "shoe size", "favorite color", "birthday", "middle name", "pet's name"]
    k = 0
    for p in names[: max(6, len(names) // 3)]:
        qs.append(Question(f"un{k}", "unsupported_answers", f"What is {p}'s {attrs[k % len(attrs)]}?", "u1", answerable=False))
        k += 1
    for z in ("Zorblax", "Quenby", "Mortimer", "Yggdra", "Plimsoll", "Wexford"):
        qs.append(Question(f"un{k}", "unsupported_answers", f"Where does {z} live?", "u1", answerable=False))
        k += 1
    for q_ in ("What is the capital of France?", "How tall is Mount Everest?", "Who wrote Hamlet?", "What is the boiling point of water in kelvin?"):
        qs.append(Question(f"un{k}", "unsupported_answers", q_, "u1", answerable=False))
        k += 1
    return Scenario("unsupported_answers", "Answerable questions mixed with questions the memory cannot answer (missing attribute, unknown entity, world knowledge).", ev, qs, "unsupported-answer prevention")


def paraphrase(rng: random.Random, scale: float) -> Scenario:
    """Facts and questions phrased in ways the rule-based extractor does or does not cover."""
    n = max(14, int(35 * scale))
    names, cities, comps = _Pool(rng, FIRST), _Pool(rng, CITIES), _Pool(rng, COMPANIES)
    templates = [
        ("covered_lives_in", "{P} lives in {C}.", "Where does {P} live?", "city"),
        ("covered_resides", "{P} resides in {C}.", "Where does {P} live?", "city"),
        ("synonym_question", "{P} works for {K}.", "Which company employs {P}?", "comp"),
        ("verb_phrase_not_covered", "{P} has been based in {C} since 2021.", "Which city is {P} based in?", "city"),
        ("inverted_sentence", "{C} is where {P} lives.", "Where does {P} live?", "city"),
        ("indirect_statement", "You can reach {P} in {C} these days.", "Where does {P} live?", "city"),
        ("question_synonym_missing", "{P} earns {N} LPA.", "How much does {P} make?", "sal"),
        ("informal_first_person", "ok so i live in {C} now lol", "Where do I live?", "city"),
        ("informal_possessive", "btw my manager is {P2}", "Who is my manager?", "p2"),
    ]
    ev: list[Event] = []
    qs: list[Question] = []
    for i in range(n):
        tag, doc, question, what = templates[i % len(templates)]
        user = f"u{i}" if tag.startswith("informal") else "u1"
        p, c, k, p2 = names.take(), cities.take(), comps.take(), names.take()
        num = rng.randrange(10, 90)
        text = doc.format(P=p, C=c, K=k, N=num, P2=p2)
        ev.append(Event(len(ev), "add", text, user, _ts(len(ev)), source_type="conversation" if tag.startswith("informal") else "user_statement"))
        gold = {"city": c, "comp": k, "sal": f"{num} LPA", "p2": p2}[what]
        qs.append(Question(f"pr{i}", "paraphrase_robustness", question.format(P=p, C=c, K=k, P2=p2), user, [gold], [], [ev[-1].idx], tag=tag))
    return Scenario("paraphrase_robustness", "Same facts in extractor-friendly, paraphrased, inverted and informal forms. Expected to expose weaknesses.", ev, qs, "robustness to phrasing")


def persistence(rng: random.Random, scale: float) -> Scenario:
    base = single_fact(rng, scale * 0.5)
    for q in base.questions:
        q.scenario = "persistence_after_restart"
    return Scenario("persistence_after_restart", "Facts stored, process restarted, then queried (disk-backed systems reopen; in-memory indexes rebuild).", base.events, base.questions, "durability", restart=True)


BUILDERS = {
    "single_fact_recall": single_fact,
    "multi_document_recall": multi_document,
    "multi_hop_reasoning": multi_hop,
    "temporal_reasoning": temporal,
    "historical_reconstruction": historical,
    "contradiction_resolution": contradiction,
    "user_personalization": personalization,
    "long_conversation": long_conversation,
    "long_document_retrieval": long_document,
    "memory_update_correction": update_correction,
    "memory_consolidation": consolidation,
    "evidence_attribution": evidence_attribution,
    "degradation_after_updates": degradation,
    "persistence_after_restart": persistence,
    "paraphrase_robustness": paraphrase,
    "unsupported_answers": unsupported,
}


def build_dataset(seed: int, scale: float = 1.0) -> dict[str, Scenario]:
    out = {}
    for name, fn in BUILDERS.items():
        out[name] = fn(random.Random(f"{seed}:{name}"), scale)
    return out


def dataset_hash(ds: dict[str, Scenario]) -> str:
    payload = json.dumps({k: [asdict(e) for e in v.events] + [asdict(q) for q in v.questions] for k, v in ds.items()}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
