"""Regenerate every figure used in the README.

    python scripts/make_figures.py

Diagrams are drawn here; all benchmark charts are computed from
benchmarks/reports/benchmark_results.json, so they can never drift from the published numbers.
Requires: pip install matplotlib
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
REPORT = ROOT / "benchmarks" / "reports" / "benchmark_results.json"
OUT.mkdir(parents=True, exist_ok=True)

INK, MUTED, LINE = "#0f172a", "#475569", "#cbd5e1"
BLUE, TEAL, AMBER, RED, VIOLET, GREEN = "#2563eb", "#0d9488", "#d97706", "#dc2626", "#7c3aed", "#16a34a"
FILL = {BLUE: "#dbeafe", TEAL: "#ccfbf1", AMBER: "#fef3c7", RED: "#fee2e2", VIOLET: "#ede9fe", GREEN: "#dcfce7", MUTED: "#f1f5f9", INK: "#e2e8f0"}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False})


def canvas(w: float, h: float, units_w: float, units_h: float):
    fig = plt.figure(figsize=(w, h), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, units_w)
    ax.set_ylim(0, units_h)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.3, 0.3), units_w - 0.6, units_h - 0.6, boxstyle="round,pad=0,rounding_size=1.5", fc="white", ec=LINE, lw=1.2))
    return fig, ax


def box(ax, x, y, w, h, title, sub="", color=BLUE, fs=9.5, subfs=7.6, dashed=False, bold=True, fill=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.9", fc=fill or FILL[color], ec=color, lw=1.4, ls="--" if dashed else "-"))
    if sub:
        ax.text(x + w / 2, y + h * 0.68, title, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", color=INK)
        ax.text(x + w / 2, y + h * 0.31, sub, ha="center", va="center", fontsize=subfs, color=MUTED, linespacing=1.35)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", color=INK)


def panel(ax, x, y, w, h, label, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2", fc="#fafafa", ec=color, lw=1.6))
    ax.text(x + 1.4, y + h - 1.9, label, ha="left", va="center", fontsize=9.5, fontweight="bold", color=color)


def arrow(ax, p, q, color=MUTED, lw=1.6):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=11, lw=lw, color=color, shrinkA=0, shrinkB=0))


def banner():
    fig = plt.figure(figsize=(16, 4), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 160)
    ax.set_ylim(0, 40)
    ax.axis("off")
    grad = np.linspace(0, 1, 256).reshape(1, -1)
    ax.imshow(grad, extent=(0, 160, 0, 40), aspect="auto", cmap=LinearSegmentedColormap.from_list("b", ["#0b1220", "#12244a", "#1d3b7a"]), zorder=0)
    rng = np.random.default_rng(4)
    pts = np.column_stack([rng.uniform(112, 158, 22), rng.uniform(3, 37, 22)])
    for p in pts:
        d = np.linalg.norm(pts - p, axis=1)
        for j in np.argsort(d)[1:3]:
            ax.plot([p[0], pts[j][0]], [p[1], pts[j][1]], color="#60a5fa", lw=0.8, alpha=0.35, zorder=1)
    ax.scatter(pts[:, 0], pts[:, 1], s=rng.uniform(18, 80, 22), c="#93c5fd", alpha=0.85, zorder=2)
    ax.set_xlim(0, 160)
    ax.set_ylim(0, 40)
    ax.add_patch(FancyBboxPatch((8, 11), 18, 18, boxstyle="round,pad=0,rounding_size=3.5", fc="#2563eb", ec="#93c5fd", lw=2, zorder=3))
    nodes = [(13, 17), (21, 17), (17, 25), (17, 15.5)]
    for a, b in [(0, 2), (1, 2), (0, 3), (1, 3), (2, 3)]:
        ax.plot([nodes[a][0], nodes[b][0]], [nodes[a][1], nodes[b][1]], color="white", lw=1.6, zorder=4)
    for n in nodes:
        ax.add_patch(Circle(n, 1.5, fc="white", ec="#1e3a8a", lw=1.2, zorder=5))
    ax.text(31, 24, "MemoraOS", fontsize=44, fontweight="bold", color="white", va="center", zorder=5)
    ax.text(31.5, 14, "Don't just give AI a bigger context window.  Give it a better memory.", fontsize=14.5, color="#bfdbfe", va="center", zorder=5)
    ax.text(31.5, 7, "local-first  ·  temporal  ·  evidence-grounded  ·  abstains when unsure  ·  benchmarked", fontsize=11, color="#93c5fd", va="center", zorder=5)
    fig.savefig(OUT / "banner.png", facecolor="#0b1220")
    plt.close(fig)


def architecture():
    fig, ax = canvas(16, 10.4, 160, 104)
    ax.text(80, 99.5, "MemoraOS architecture", ha="center", fontsize=15, fontweight="bold", color=INK)
    panel(ax, 3, 82, 154, 13, "INTERFACES  (one engine behind all of them)", MUTED)
    names = [("Python API", "MemoryOS"), ("REST API", "FastAPI · keys · roles"), ("MCP server", "stdio · fixed user"), ("CLI", "memoraos ..."), ("TypeScript SDK", "@memoraos/sdk"), ("Dashboard", "Next.js · live data")]
    for i, (t, s) in enumerate(names):
        box(ax, 5 + i * 25.1, 83.2, 23.2, 7.2, t, s, MUTED, fs=8.8, subfs=7)
    panel(ax, 3, 37, 52, 42, "WRITE PATH   remember()", BLUE)
    steps = [("1  Redact secrets · chunk", "originals kept verbatim"), ("2  Classify", "episodic · semantic · procedural"), ("3  Extract facts · entities · dates", "valid-from / valid-until"), ("4  Deduplicate · embed", "content-hash embedding cache")]
    for i, (t, s) in enumerate(steps):
        y = 65 - i * 8.8
        box(ax, 6, y, 46, 7, t, s, BLUE, fs=8.8, subfs=7.2)
        if i < 3:
            arrow(ax, (29, y), (29, y - 1.8), BLUE)
    panel(ax, 59, 37, 98, 42, "READ PATH   recall()", TEAL)
    stages = [("Query analysis", "cues · time refs\nentities · identifiers"), ("Adaptive router", "scores · cost-aware\nfallback plan"), ("Run strategies", "first supported\noutcome wins"), ("Truth engine", "timelines · conflicts\nreliability · support")]
    for i, (t, s) in enumerate(stages):
        x = 61 + i * 24.2
        box(ax, x, 58, 22, 13, t, s, TEAL, fs=8.8, subfs=7)
        if i < 3:
            arrow(ax, (x + 22, 64.5), (x + 24.2, 64.5), TEAL)
    chips = ["exact", "temporal", "bm25", "vector", "hybrid", "graph", "episodic", "procedural", "multistage", "latent*"]
    ax.text(61, 55.6, "strategies available to the router", fontsize=7.4, color=MUTED, va="center", style="italic")
    for i, c in enumerate(chips):
        box(ax, 61 + i * 9.1, 49.4, 8.4, 4.2, c, "", AMBER if c == "latent*" else TEAL, fs=6.8, dashed=(c == "latent*"), bold=False, fill="white")
    arrow(ax, (120.4, 58), (120.4, 55.9), TEAL, lw=1.1)
    ax.add_patch(FancyBboxPatch((61, 38.4), 90, 9.4, boxstyle="round,pad=0,rounding_size=0.9", fc="white", ec=LINE, lw=1.2))
    box(ax, 62.5, 39.4, 41, 7.4, "Answer + evidence", "source ids · excerpts · dates · reliability", GREEN, fs=8.6, subfs=6.9)
    ax.text(106.5, 43.1, "or", ha="center", va="center", fontsize=8.5, color=MUTED, style="italic")
    box(ax, 109.5, 39.4, 40, 7.4, "insufficient_evidence", "never a guess; near-misses only in explain()", RED, fs=8.6, subfs=6.9)
    ax.plot([153.6, 153.6], [58, 43.1], color=TEAL, lw=1.6)
    ax.plot([151, 153.6], [43.1, 43.1], color=TEAL, lw=1.6)
    arrow(ax, (153.6, 58), (153.6, 57.9), TEAL)
    arrow(ax, (153.6, 43.1), (151.1, 43.1), TEAL)
    for x in (30, 108):
        arrow(ax, (x, 82), (x, 79.3), MUTED)
    panel(ax, 3, 20, 154, 14, "CROSS-CUTTING", VIOLET)
    cross = [("Consolidation", "derived summaries · links\nreversible · originals untouched", VIOLET, False), ("Time travel & audit", "as-of recall · versions\nhash-chained event log", VIOLET, False),
             ("Isolation & privacy", "tenant · user · scope visibility\nredaction · hard delete · export", VIOLET, False), ("Optional providers", "Ollama · OpenAI-compatible\nretries · fallback · usage", AMBER, True)]
    for i, (t, s, c, d) in enumerate(cross):
        box(ax, 5 + i * 37.7, 21, 35.5, 9.4, t, s, c, fs=8.8, subfs=7, dashed=d)
    panel(ax, 3, 3, 154, 14.5, "STORAGE   one SQLite file (WAL, versioned migrations, online backup)", INK)
    tables = ["sources", "memories +\nversions", "FTS5 / BM25", "embeddings\ncache", "facts\n(bitemporal)", "mentions ·\naliases · links", "events\n(hash chain)", "retrieval log ·\nfeedback"]
    for i, t in enumerate(tables):
        box(ax, 5 + i * 19.1, 4.4, 17.6, 8, t, "", MUTED, fs=7.6, bold=False, fill="white")
    for x in (30, 108):
        arrow(ax, (x, 37), (x, 34.3), MUTED)
    arrow(ax, (80, 20), (80, 17.7), MUTED)
    fig.savefig(OUT / "architecture.png")
    plt.close(fig)


REAL_REPORT = ROOT / "benchmarks" / "reports" / "real_docs_results.json"


def _real_engine():
    """An engine filled with REAL data only: the project's docs and the dated CPython release history."""
    import sys

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    from benchmarks import real_docs
    from memoraos import MemoryOS

    mem = MemoryOS.in_memory()
    scenario, origin, _sha = real_docs.build()
    for ev in scenario.events:
        mem.remember(ev.text, user_id="me", source_type="document", origin=origin[ev.idx])
    data = json.loads((ROOT / "data" / "python_releases.json").read_text(encoding="utf-8"))
    return mem, data


def routing():
    mem, _data = _real_engine()
    data = json.loads((ROOT / "data" / "python_releases.json").read_text(encoding="utf-8"))
    for rec in data["records"]:
        mem.remember_json({k: rec[k] for k in ("subject", "predicate", "object", "valid_from")}, user_id="me")
    questions = [
        ("What is the latest version of Python 3.14?", BLUE),
        ("What was the latest version of Python 3.14 in March 2026?", TEAL),
        ("How is Memorilla related to SlotAttentionMemory?", VIOLET),
        ("How do I run the benchmark?", AMBER),
        ("What happened before the CI test failed on Windows?", GREEN),
        ("Find test_temporal_memory", RED),
        ("Summarize everything about latent memory", BLUE),
    ]
    fig, ax = canvas(16, 8.4, 160, 84)
    ax.text(80, 79.5, "Adaptive routing on real questions: different questions, different strategies", ha="center", fontsize=14, fontweight="bold", color=INK)
    for x, t in [(5, "Question"), (58, "Category (scored 0-1)"), (89, "Strategy that answered"), (118, "Strategies tried, in order")]:
        ax.text(x, 73, t, fontsize=9, fontweight="bold", color=MUTED)
    for i, (q, c) in enumerate(questions):
        r = mem.recall(q, user_id="me", use_cache=False)
        y = 62 - i * 8.6
        top = max(v for k, v in r.plan.scores.items() if k.startswith("cat:"))
        box(ax, 5, y, 49, 6.4, "“" + q + "”", "", MUTED, fs=7.4, bold=False, fill="#f8fafc")
        arrow(ax, (54, y + 3.2), (58, y + 3.2), MUTED, lw=1.2)
        box(ax, 58, y, 28, 6.4, f"{r.plan.category}  ({top:.2f})", "", c, fs=8.2)
        arrow(ax, (86, y + 3.2), (89, y + 3.2), MUTED, lw=1.2)
        box(ax, 89, y, 26.5, 6.4, f"{r.strategy}  ·  {r.status.replace('insufficient_evidence', 'refused')}", "", c, fs=8.2)
        box(ax, 118, y, 37, 6.4, " → ".join(r.strategies_tried), "", MUTED, fs=8, bold=False, fill="white")
    ax.text(80, 3.4, "Every row was produced by running the router on a store holding MemoraOS's own documentation and the PSF's CPython release dates (data/python_releases.json).", ha="center", fontsize=7.6, color=MUTED)
    fig.savefig(OUT / "routing.png")
    plt.close(fig)
    mem.close()


def temporal():
    from memoraos import MemoryOS

    data = json.loads((ROOT / "data" / "python_releases.json").read_text(encoding="utf-8"))
    stable = [r for r in data["records"] if r["predicate"] == "latest stable version"]
    mem = MemoryOS.in_memory()
    order = [stable[1], stable[2], stable[0]]  # recorded out of order on purpose: 3.13, 3.14, then 3.12
    for r in order:
        mem.remember_json({k: r[k] for k in ("subject", "predicate", "object", "valid_from")}, user_id="me")
    asks = [
        ("“latest stable Python?”", "What is the latest stable version of Python?", {}),
        ("“… before October 2024?”", "What was the latest stable version of Python before October 2024?", {}),
        ("“… in June 2025?”", "What was the latest stable version of Python in June 2025?", {}),
        ("“previous stable version?”", "What was the previous latest stable version of Python?", {}),
    ]
    answers = [(label, mem.recall(q, user_id="me", **kw).answer.split(" (")[0]) for label, q, kw in asks]
    mem.close()
    fig, ax = canvas(16, 7.6, 160, 76)
    ax.text(80, 71.5, "Bitemporal facts on real data: CPython release dates (PEP 693 · 719 · 745)", ha="center", fontsize=14, fontweight="bold", color=INK)
    ax.text(6, 64, "Valid time  (when it became the latest stable version)", fontsize=9.5, fontweight="bold", color=BLUE)
    base = 51
    ax.plot([10, 150], [base, base], color=INK, lw=1.8)
    xs = {"2023-10-02": 28, "2024-10-07": 74, "2025-10-07": 120}
    for d, x in xs.items():
        ax.plot([x, x], [base - 1, base + 1], color=INK, lw=1.5)
        ax.text(x, base - 3.4, d, ha="center", fontsize=8.6, color=INK)
    cuts = [28, 74, 120, 148]
    for i, r in enumerate(stable):
        cur = i == len(stable) - 1
        box(ax, cuts[i] + 0.6, base + 2.5, cuts[i + 1] - cuts[i] - 1.2, 6.5, "Python " + r["object"], "", GREEN if cur else MUTED, fs=10)
        ax.text((cuts[i] + cuts[i + 1]) / 2, base + 11.3, "current" if cur else "historical", ha="center", fontsize=7.8, color=GREEN if cur else MUTED, style="italic")
    ax.text(6, 38, "System time  (the order MemoraOS actually learned them in; recorded out of order, still resolved by valid time)", fontsize=9.5, fontweight="bold", color=VIOLET)
    for i, r in enumerate(order):
        box(ax, 22 + i * 44, 26.5, 30, 8, "Python " + r["object"], f"recorded {['1st', '2nd', '3rd'][i]}", VIOLET, fs=9, subfs=7.2)
    ax.text(6, 20, "Queries (answers computed by running the engine)", fontsize=9.5, fontweight="bold", color=TEAL)
    for i, (q, a) in enumerate(answers):
        box(ax, 8 + i * 37.5, 5, 34, 11.5, q, "→ Python " + a if a[0].isdigit() else "→ " + a, TEAL, fs=8.2, subfs=8)
    fig.text(0.01, 0.005, "Source: peps.python.org/pep-0693, pep-0719, pep-0745 · retrieved 2026-11-17 · public domain / CC0", fontsize=7.2, color=MUTED)
    fig.savefig(OUT / "temporal.png")
    plt.close(fig)


def real_docs_chart(rep):
    """Precision/recall on real documentation: answerable answered correctly vs unanswerable refused."""
    names = {"bm25": "BM25 RAG", "vector": "Vector RAG", "hybrid_rag": "Hybrid RAG", "hybrid_rag_top1": "Hybrid RAG (1 sentence)", "hybrid_rag_gated": "Hybrid RAG + abstain gate", "memoraos": "MemoraOS (default)", "memoraos[anchor=0.4]": "MemoraOS anchor 0.4", "memoraos[anchor=0.25]": "MemoraOS anchor 0.25", "memoraos[anchor=0.0]": "MemoraOS anchor 0"}
    fig, ax = plt.subplots(figsize=(10.4, 5.6), dpi=150)
    by = rep["by_kind"]

    # every question (dev + held-out), answerable vs unanswerable
    def rates(k):
        ans = (by[k]["dev:answerable"] * 30 + by[k]["heldout:answerable"] * 16) / 46
        una = (by[k]["dev:unanswerable"] * 12 + by[k]["heldout:unanswerable"] * 6) / 18
        return 100 * una, 100 * ans

    for k, label in names.items():
        if k not in by:
            continue
        x, y = rates(k)
        ours = k.startswith("memoraos")
        ax.scatter(x, y, s=170 if k == "memoraos" else 95, color=BLUE if ours else "#94a3b8", edgecolor=INK if k == "memoraos" else "white", lw=1.6, zorder=3)
        ax.annotate(label, (x, y), textcoords="offset points", xytext=(9, 6), fontsize=8.2, color=INK, fontweight="bold" if k == "memoraos" else "normal")
    ours_pts = sorted(rates(k) for k in names if k.startswith("memoraos") and k in by)
    ax.plot([p[0] for p in ours_pts], [p[1] for p in ours_pts], color=BLUE, lw=1.4, alpha=0.5, zorder=2)
    ax.set_xlabel("Unanswerable questions correctly refused (%)  →  fewer wrong answers")
    ax.set_ylabel("Answerable questions answered correctly (%)  →  more useful")
    ax.set_xlim(-5, 112)
    ax.set_ylim(35, 108)
    ax.grid(alpha=0.25)
    ax.set_title("Real documentation, 64 questions: the precision / recall trade-off", fontsize=11.5, fontweight="bold", loc="left")
    c = rep["corpus"]
    fig.text(0.01, 0.005, f"Corpus: MemoraOS's own docs ({c['files']} files, {c['sections']} sections, sha256 {c['sha256'][:10]}…) · project-authored questions · mechanical scoring · no LLM", fontsize=7.4, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(OUT / "benchmark_real_docs.png")
    plt.close(fig)


NICE = {"bm25": "BM25 RAG", "vector": "Vector RAG", "hybrid_rag": "Hybrid RAG\n(RRF)", "hybrid_rag_gated": "Hybrid RAG\n+ abstain gate", "memoraos_hybrid_only": "MemoraOS\nhybrid-only\n(ablation)", "memoraos": "MemoraOS"}
ORDER = list(NICE)
COL = {"bm25": "#94a3b8", "vector": "#94a3b8", "hybrid_rag": "#94a3b8", "hybrid_rag_gated": "#64748b", "memoraos_hybrid_only": "#7c9be0", "memoraos": BLUE}


def bench_overall(rep):
    m = rep["metrics"]
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
    vals = [100 * m[s]["pooled_accuracy"] for s in ORDER]
    lo = [100 * (m[s]["pooled_accuracy"] - m[s]["pooled_accuracy_ci95"][0]) for s in ORDER]
    hi = [100 * (m[s]["pooled_accuracy_ci95"][1] - m[s]["pooled_accuracy"]) for s in ORDER]
    bars = ax.bar(range(len(ORDER)), vals, yerr=[lo, hi], color=[COL[s] for s in ORDER], capsize=4, width=0.66, error_kw={"lw": 1.3, "ecolor": INK})
    for b, v in zip(bars, vals, strict=True):
        ax.text(b.get_x() + b.get_width() / 2, v + 4.2, f"{v:.1f}%", ha="center", fontsize=10.5, fontweight="bold", color=INK)
    ax.set_xticks(range(len(ORDER)), [NICE[s] for s in ORDER], fontsize=9)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Pooled accuracy (%)")
    ax.set_title(f"Accuracy across {len(m['memoraos']['scenarios'])} scenarios (3 seeds; error bars = 95% bootstrap CI)", fontsize=11.5, fontweight="bold", loc="left")
    ax.grid(axis="y", alpha=0.25)
    cfg = rep["configuration"]
    fig.text(0.01, 0.005, f"Synthetic project-authored datasets · {cfg['embedder'].split(' (')[0]} · no LLM · seeds {cfg['seeds']} · digest {rep['deterministic_digest'][:12]}", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(OUT / "benchmark_overall.png")
    plt.close(fig)


def bench_heatmap(rep):
    m = rep["metrics"]
    scen = list(m["memoraos"]["scenarios"])
    data = np.array([[100 * m[s]["scenarios"][sc]["accuracy"] for s in ORDER] for sc in scen])
    fig, ax = plt.subplots(figsize=(12, 8.6), dpi=150)
    ax.imshow(data, cmap=LinearSegmentedColormap.from_list("rg", ["#ef4444", "#fbbf24", "#22c55e"]), vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(ORDER)), [NICE[s].replace("\n", " ") for s in ORDER], rotation=18, ha="right", fontsize=8.5)
    ax.set_yticks(range(len(scen)), [s.replace("_", " ") for s in scen], fontsize=9)
    for i in range(len(scen)):
        for j in range(len(ORDER)):
            ax.text(j, i, f"{data[i, j]:.0f}", ha="center", va="center", fontsize=9, color=INK, fontweight="bold" if ORDER[j] == "memoraos" else "normal")
    ax.add_patch(plt.Rectangle((len(ORDER) - 1.5, -0.5), 1, len(scen), fill=False, ec=BLUE, lw=2.5))
    ax.set_title("Accuracy (%) by scenario and system (synthetic, project-authored datasets)", fontsize=12, fontweight="bold", loc="left")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    fig.tight_layout()
    fig.savefig(OUT / "benchmark_scenarios.png", bbox_inches="tight")
    plt.close(fig)


def bench_degradation(rep):
    d = rep["degradation_curve"]
    fig, ax = plt.subplots(figsize=(8.6, 4.6), dpi=150)
    xs: list[int] = []
    for s in ORDER:
        tags = sorted(d[s], key=lambda t: int(t.split("_")[1]))
        xs = [int(t.split("_")[1]) for t in tags]
        ax.plot(range(len(xs)), [100 * d[s][t] for t in tags], marker="o", lw=3 if s == "memoraos" else 1.6, color=COL[s], label=NICE[s].replace("\n", " "), zorder=3 if s == "memoraos" else 2)
    ax.set_xticks(range(len(xs)), [str(x) for x in xs])
    ax.set_xlabel("Times each fact was overwritten")
    ax.set_ylabel("Accuracy on the latest value (%)")
    ax.set_ylim(-4, 108)
    ax.grid(alpha=0.25)
    ax.set_title("Memory degradation after repeated updates", fontsize=11.5, fontweight="bold", loc="left")
    ax.legend(fontsize=7.6, loc="center right", frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "benchmark_degradation.png")
    plt.close(fig)


def bench_costs(rep):
    m = rep["metrics"]
    systems = ["bm25", "hybrid_rag", "memoraos"]

    def avg(s, key):
        v = [x[key] for x in m[s]["scenarios"].values()]
        return sum(v) / len(v)

    def med(s, key):
        v = sorted(x[key] for x in m[s]["scenarios"].values())
        return v[len(v) // 2]

    panels = [("Update cost\n(ms / event, lower is better)", lambda s: avg(s, "ingest_ms_per_event")), ("Query latency p50\n(ms, lower is better)", lambda s: med(s, "latency_ms_p50")),
              ("Storage ÷ raw text\n(× on tiny texts, lower is better)", lambda s: avg(s, "storage_overhead_ratio")), ("Evidence tokens / question\n(lower is better)", lambda s: avg(s, "mean_context_tokens"))]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.8), dpi=150)
    for ax, (title, fn) in zip(axes, panels, strict=True):
        vals = [fn(s) for s in systems]
        bars = ax.bar(range(3), vals, color=[COL[s] for s in systems], width=0.62)
        for b, v in zip(bars, vals, strict=True):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.02, f"{v:.1f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.set_xticks(range(3), ["BM25", "Hybrid", "MemoraOS"], fontsize=8.5)
        ax.set_title(title, fontsize=9, loc="left")
        ax.set_ylim(0, max(vals) * 1.22)
        ax.tick_params(axis="y", labelsize=7.5)
    fig.suptitle("What the accuracy costs (measured on the same machine)", x=0.01, ha="left", fontsize=11.5, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(OUT / "benchmark_costs.png")
    plt.close(fig)


if __name__ == "__main__":
    banner()
    architecture()
    routing()
    temporal()
    if REAL_REPORT.exists():
        real_docs_chart(json.loads(REAL_REPORT.read_text(encoding="utf-8")))
    if REPORT.exists():
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        bench_overall(report)
        bench_heatmap(report)
        bench_degradation(report)
        bench_costs(report)
    print("figures written to", OUT)
