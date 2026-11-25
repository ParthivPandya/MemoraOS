"use client";

import { useEffect, useRef, useState } from "react";

type Item = { memory_id: string; excerpt: string };
type Run = { excluded: string[]; answer: string; status: string; answer_changed: boolean; status_changed: boolean };
type Replay = { baseline: { answer: string; status: string }; baseline_matches_logged: boolean; note: string; runs: Run[] };

const tone = (s: string) => (s === "answered" ? "ok" : s === "conflict" ? "warn" : "bad");

/** Tick cited memories to remove them and re-run the question on a temporary copy of the store (the live store is never changed). */
export default function ReplayLab({ recallId, items }: { recallId: string; items: Item[] }) {
  const [off, setOff] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<Replay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    if (off.size === 0) {
      setResult(null);
      setError(null);
      return;
    }
    const mine = ++seq.current;
    setBusy(true);
    const timer = setTimeout(async () => {
      try {
        const res = await fetch("/api/replay", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ recall_id: recallId, exclude: [...off] }) });
        const data = await res.json();
        if (mine !== seq.current) return;
        if (!res.ok) setError(String(data?.detail ?? res.status));
        else {
          setError(null);
          setResult(data as Replay);
        }
      } catch (e) {
        if (mine === seq.current) setError((e as Error).message);
      } finally {
        if (mine === seq.current) setBusy(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [off, recallId]);

  const toggle = (id: string) =>
    setOff((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const run = result?.runs[0];

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="k">Counterfactual replay: remove evidence and watch the answer</div>
      <div role="group" aria-label="Cited memories to remove" style={{ margin: "8px 0" }}>
        {items.map((it) => (
          <label key={it.memory_id} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "4px 0", cursor: "pointer" }}>
            <input type="checkbox" checked={off.has(it.memory_id)} onChange={() => toggle(it.memory_id)} style={{ marginTop: 3 }} />
            <span>{it.excerpt.slice(0, 180)}<span className="mono"> {it.memory_id}</span></span>
          </label>
        ))}
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {off.size === 0 ? <p className="sub" style={{ margin: 0 }}>Tick one or more memories to remove them from a copy of the store and re-run the question.</p> : (
        <div aria-live="polite" style={{ opacity: busy ? 0.5 : 1 }}>
          {!run || !result ? <p className="sub" style={{ margin: 0 }}>Replaying…</p> : (
            <table style={{ marginBottom: 8 }}><thead><tr><th>Store</th><th>Answer</th></tr></thead><tbody>
              <tr><td>With everything</td><td>{result.baseline.answer} <span className={`badge ${tone(result.baseline.status)}`}>{result.baseline.status}</span></td></tr>
              <tr><td>Without {off.size} selected</td><td>{run.answer} <span className={`badge ${tone(run.status)}`}>{run.status}</span>{" "}
                {run.answer_changed || run.status_changed ? <span className="badge warn">{run.status_changed ? "status changed" : "answer changed"}</span> : <span className="badge">unchanged</span>}</td></tr>
            </tbody></table>
          )}
          {result && <p className="sub" style={{ margin: 0 }}>{result.baseline_matches_logged ? "" : "The store changed since this recall, so the baseline differs from the logged answer. "}{result.note}</p>}
        </div>
      )}
    </div>
  );
}
