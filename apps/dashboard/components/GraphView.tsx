"use client";

import { useMemo, useState } from "react";

export type GNode = { id: string; label: string; degree: number };
export type GEdge = { source: string; target: string; predicate: string; kind: string; memory_id: string };

const W = 900, H = 560;

/** Deterministic circular layout; hub nodes are placed on an inner ring. */
export default function GraphView({ nodes, edges }: { nodes: GNode[]; edges: GEdge[] }) {
  const [sel, setSel] = useState<string | null>(null);
  const pos = useMemo(() => {
    const sorted = [...nodes].sort((a, b) => b.degree - a.degree || a.id.localeCompare(b.id));
    const m = new Map<string, { x: number; y: number }>();
    const inner = sorted.slice(0, Math.max(1, Math.floor(sorted.length / 4)));
    const outer = sorted.slice(inner.length);
    inner.forEach((n, i) => { const a = (2 * Math.PI * i) / inner.length; m.set(n.id, { x: W / 2 + 130 * Math.cos(a), y: H / 2 + 130 * Math.sin(a) }); });
    outer.forEach((n, i) => { const a = (2 * Math.PI * i) / outer.length; m.set(n.id, { x: W / 2 + 240 * Math.cos(a), y: H / 2 + 220 * Math.sin(a) }); });
    return m;
  }, [nodes]);
  const touching = edges.filter((e) => sel && (e.source === sel || e.target === sel));
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Knowledge graph" style={{ width: "100%", background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}>
        {edges.map((e, i) => {
          const a = pos.get(e.source), b = pos.get(e.target);
          if (!a || !b) return null;
          const hot = sel && (e.source === sel || e.target === sel);
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={hot ? "var(--accent)" : "var(--border)"} strokeDasharray={e.kind === "mention" ? "4 3" : undefined} strokeWidth={hot ? 2 : 1} />;
        })}
        {nodes.map((n) => {
          const p = pos.get(n.id)!;
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} onClick={() => setSel(n.id === sel ? null : n.id)} style={{ cursor: "pointer" }} tabIndex={0} role="button" aria-label={n.label}>
              <circle r={6 + Math.min(10, n.degree)} fill={n.id === sel ? "var(--accent)" : "#2a3646"} stroke="var(--accent)" />
              <text y={-12 - Math.min(10, n.degree)} textAnchor="middle" fontSize="11" fill="var(--text)">{n.label}</text>
            </g>
          );
        })}
      </svg>
      <p className="sub">Solid lines: extracted relationships. Dashed: co-mentioned in the same memory. Click a node to list its edges.</p>
      {sel && (
        <table><thead><tr><th>Edge</th><th>Type</th><th>Memory</th></tr></thead><tbody>
          {touching.map((e, i) => <tr key={i}><td>{e.source} —[{e.predicate}]→ {e.target}</td><td>{e.kind}</td><td className="mono">{e.memory_id}</td></tr>)}
        </tbody></table>
      )}
    </>
  );
}
