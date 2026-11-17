"use client";

import { useState } from "react";

type Evidence = { memory_id: string; source_id: string | null; excerpt: string; kind: string; source_type: string | null; source_reliability: number | null; verification: string | null; effective_at: string | null; flags: string[] };
type Result = {
  answer: string; status: string; strategy: string; strategies_tried: string[]; fallback_used: boolean; evidence: Evidence[];
  contradictions: { values: string[]; kind: string; resolved: boolean; justification: string }[];
  timeline: { value: string; status: string; valid_from: string | null; valid_until: string | null; inferred_start: boolean }[];
  confidence: Record<string, number | string | null>; plan: { category: string; scores: Record<string, number>; reasons: string[]; stages: string[] };
  latency_ms: number; context_tokens: number; flags: string[]; cached: boolean;
};

const STRATEGIES = ["", "exact", "bm25", "vector", "hybrid", "graph", "temporal", "episodic", "procedural", "multistage"];

export default function Playground() {
  const [query, setQuery] = useState("");
  const [asOf, setAsOf] = useState("");
  const [strategy, setStrategy] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    const r = await fetch("/api/recall", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, as_of: asOf, strategy }) });
    const data = await r.json();
    if (!r.ok) { setErr(String(data.detail ?? "request failed")); setRes(null); } else setRes(data);
    setBusy(false);
  }

  return (
    <>
      <h2>Search playground</h2>
      <p className="sub">Ask a question; see the chosen strategy, fallbacks, evidence and the separate confidence signals.</p>
      <form onSubmit={run} className="row" aria-label="Recall form">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="What is my current salary?" aria-label="Question" required maxLength={2000} />
        <input value={asOf} onChange={(e) => setAsOf(e.target.value)} placeholder="as of (ISO date, optional)" aria-label="As of" style={{ maxWidth: 200, flex: "none" }} />
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)} aria-label="Force strategy">
          {STRATEGIES.map((s) => <option key={s} value={s}>{s || "auto (router)"}</option>)}
        </select>
        <button disabled={busy}>{busy ? "…" : "Recall"}</button>
      </form>
      {err && <div className="error" role="alert">{err}</div>}
      {res && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="k">Answer <span className={`badge ${res.status === "answered" ? "ok" : res.status === "conflict" ? "warn" : "bad"}`}>{res.status}</span></div>
            <div style={{ fontSize: 16, margin: "6px 0" }}>{res.answer}</div>
            <div className="mono">strategy {res.strategy} · tried [{res.strategies_tried.join(" → ")}]{res.fallback_used ? " · fallback used" : ""} · {res.latency_ms} ms · ~{res.context_tokens} context tokens{res.cached ? " · cached" : ""}</div>
            {res.flags.length > 0 && <div className="badge bad">{res.flags.join(", ")}</div>}
          </div>
          <h3>Routing</h3>
          <table><tbody>
            <tr><td>Category</td><td>{res.plan.category}</td></tr>
            <tr><td>Reasons</td><td>{res.plan.reasons.join("; ")}</td></tr>
            <tr><td>Strategy scores</td><td className="mono">{Object.entries(res.plan.scores).filter(([k]) => !k.startsWith("cat:")).map(([k, v]) => `${k}=${v}`).join("  ")}</td></tr>
          </tbody></table>
          <h3>Confidence (kept separate on purpose)</h3>
          <table><tbody>{Object.entries(res.confidence).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v == null ? "–" : String(v)}</td></tr>)}</tbody></table>
          {res.timeline.length > 0 && <>
            <h3>Value timeline</h3>
            <table><thead><tr><th>Value</th><th>Status</th><th>Valid from</th><th>Valid until</th></tr></thead><tbody>
              {res.timeline.map((t, i) => <tr key={i}><td>{t.value}</td><td>{t.status}</td><td>{t.valid_from?.slice(0, 10) ?? (t.inferred_start ? "unknown (ordered by recording time)" : "–")}</td><td>{t.valid_until?.slice(0, 10) ?? "–"}</td></tr>)}
            </tbody></table></>}
          {res.contradictions.length > 0 && <>
            <h3>Contradictions</h3>
            <table><tbody>{res.contradictions.map((c, i) => <tr key={i}><td>{c.values.join(" vs ")}</td><td>{c.kind}{c.resolved ? " (resolved)" : " (OPEN)"}</td><td>{c.justification}</td></tr>)}</tbody></table></>}
          <h3>Evidence inspector</h3>
          {res.evidence.length === 0 ? <div className="empty">No supporting evidence.</div> : (
            <table><thead><tr><th>Excerpt</th><th>Kind</th><th>Source</th><th>Effective</th></tr></thead><tbody>
              {res.evidence.map((e) => (
                <tr key={e.memory_id + e.excerpt}>
                  <td>{e.excerpt}<div className="mono">{e.memory_id} · {e.source_id}</div>{e.flags.map((f) => <span key={f} className="badge warn">{f}</span>)}</td>
                  <td>{e.kind}</td>
                  <td>{e.source_type} · reliability {e.source_reliability?.toFixed(2)} · {e.verification}</td>
                  <td className="mono">{e.effective_at?.slice(0, 10) ?? "–"}</td>
                </tr>
              ))}
            </tbody></table>
          )}
        </>
      )}
    </>
  );
}
