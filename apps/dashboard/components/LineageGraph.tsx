type LNode = { memory_id: string; excerpt: string };
type LEdge = { src: string; dst: string; kind: string };

const COLORS: Record<string, string> = { causes: "var(--accent)", solves: "var(--ok)", supersedes: "var(--warn)", blocked_by: "var(--bad)" };
const NODE_W = 190, NODE_H = 54, GAP_X = 70, GAP_Y = 18, PAD = 16;

/** Layered left-to-right drawing of explicit causal links (an arrow points from the memory that "causes/solves/supersedes" to its target). */
export default function LineageGraph({ nodes, edges, cited }: { nodes: LNode[]; edges: LEdge[]; cited: string[] }) {
  const ids = [...new Set(nodes.map((n) => n.memory_id))];
  const text = new Map(nodes.map((n) => [n.memory_id, n.excerpt]));
  const layer = new Map(ids.map((id) => [id, 0]));
  for (let pass = 0; pass < ids.length; pass++) {
    let moved = false;
    for (const e of edges) {
      const next = (layer.get(e.src) ?? 0) + 1;
      if (layer.has(e.dst) && next > (layer.get(e.dst) ?? 0) && next < ids.length) {
        layer.set(e.dst, next);
        moved = true;
      }
    }
    if (!moved) break;
  }
  const columns: string[][] = [];
  for (const id of ids) (columns[layer.get(id) ?? 0] ??= []).push(id);
  const pos = new Map<string, { x: number; y: number }>();
  columns.forEach((col, c) => (col ?? []).forEach((id, r) => pos.set(id, { x: PAD + c * (NODE_W + GAP_X), y: PAD + r * (NODE_H + GAP_Y) })));
  const width = PAD * 2 + columns.length * NODE_W + (columns.length - 1) * GAP_X;
  const height = PAD * 2 + Math.max(1, ...columns.map((c) => c?.length ?? 0)) * (NODE_H + GAP_Y) - GAP_Y;
  const kinds = [...new Set(edges.map((e) => e.kind))];

  return (
    <>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Causal lineage graph" style={{ width: "100%", maxHeight: 520, background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}>
        <defs>
          {kinds.map((k) => (
            <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={COLORS[k] ?? "var(--muted)"} />
            </marker>
          ))}
        </defs>
        {edges.map((e, i) => {
          const a = pos.get(e.src), b = pos.get(e.dst);
          if (!a || !b) return null;
          const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
          const mx = (x1 + x2) / 2;
          const same = a.x === b.x;
          const d = same ? `M ${a.x + NODE_W / 2} ${a.y + NODE_H} L ${b.x + NODE_W / 2} ${b.y}` : `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
          return (
            <g key={i}>
              <path d={d} fill="none" stroke={COLORS[e.kind] ?? "var(--muted)"} strokeWidth={1.6} markerEnd={`url(#arrow-${e.kind})`} />
              <text x={same ? a.x + NODE_W / 2 + 6 : mx} y={same ? (a.y + NODE_H + b.y) / 2 : (y1 + y2) / 2 - 5} textAnchor={same ? "start" : "middle"} fontSize="10" fill={COLORS[e.kind] ?? "var(--muted)"}>{e.kind}</text>
            </g>
          );
        })}
        {ids.map((id) => {
          const p = pos.get(id)!;
          const words = (text.get(id) ?? "").replace(/\s+/g, " ").split(" ");
          const lines: string[] = [""];
          for (const w of words) {
            const cur = lines[lines.length - 1] ?? "";
            if ((cur + " " + w).trim().length <= 30) lines[lines.length - 1] = (cur + " " + w).trim();
            else if (lines.length < 2) lines.push(w);
            else {
              lines[1] = ((lines[1] ?? "") + "…").slice(0, 30);
              break;
            }
          }
          const t = words.join(" ");
          return (
            <g key={id} transform={`translate(${p.x},${p.y})`}>
              <rect width={NODE_W} height={NODE_H} rx={6} fill="#1b2430" stroke={cited.includes(id) ? "var(--accent)" : "var(--border)"} strokeWidth={cited.includes(id) ? 2 : 1} />
              <text x={8} y={16} fontSize="10" fill="var(--muted)">{id.slice(0, 26)}</text>
              <text x={8} y={32} fontSize="11" fill="var(--text)">{lines[0]}</text>
              <text x={8} y={46} fontSize="11" fill="var(--text)">{lines[1] ?? ""}</text>
              <title>{t}</title>
            </g>
          );
        })}
      </svg>
      <p className="sub">Arrows point from the memory that causes, solves or supersedes to its target. Blue outline: memories cited by this answer. Links are only the ones recorded explicitly.</p>
    </>
  );
}
