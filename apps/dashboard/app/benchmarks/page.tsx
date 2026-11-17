import { Empty, ErrorBox, Header, pct } from "@/components/ui";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Scen = { n: number; accuracy: number };
type Report = {
  generated_at: string; command: string; deterministic_digest: string;
  configuration: { seeds: number[]; embedder: string; llm_used: boolean };
  metrics: Record<string, { macro_accuracy: number; pooled_accuracy: number; pooled_accuracy_ci95: [number, number]; scenarios: Record<string, Scen> }>;
  external_systems: { system: string; executed: boolean; reason: string }[];
};

export default async function Benchmarks() {
  const r = await api<Report[]>("/v1/benchmarks");
  const rep = r.ok ? r.data[0] : null;
  const order = ["bm25", "vector", "hybrid_rag", "hybrid_rag_top1", "hybrid_rag_gated", "memoraos_hybrid_only", "memoraos"];
  const systems = rep ? order.filter((s) => s in rep.metrics) : [];
  const scen = rep && systems.length ? Object.keys(rep.metrics[systems[0]].scenarios) : [];
  return (
    <>
      <Header title="Benchmark comparison" sub="Rendered from benchmarks/reports/benchmark_results.json produced by `python -m benchmarks.run`." />
      {!r.ok ? <ErrorBox message={r.error} /> : !rep ? <Empty>No benchmark report found. Run: python -m benchmarks.run</Empty> : (
        <>
          <p className="mono">{rep.command} · generated {rep.generated_at} · seeds {rep.configuration.seeds.join(",")} · digest {rep.deterministic_digest.slice(0, 12)}</p>
          <p className="sub">Synthetic, project-authored datasets; {rep.configuration.embedder}; LLM used: {String(rep.configuration.llm_used)}. See the full report for limitations.</p>
          <table><thead><tr><th>System</th><th>Macro accuracy</th><th>Pooled accuracy [95% CI]</th></tr></thead><tbody>
            {systems.map((s) => <tr key={s}><td>{s}</td><td>{pct(rep.metrics[s].macro_accuracy)}</td><td>{pct(rep.metrics[s].pooled_accuracy)} [{pct(rep.metrics[s].pooled_accuracy_ci95[0])}, {pct(rep.metrics[s].pooled_accuracy_ci95[1])}]</td></tr>)}
          </tbody></table>
          <table><thead><tr><th>Scenario</th>{systems.map((s) => <th key={s}>{s}</th>)}</tr></thead><tbody>
            {scen.map((sc) => <tr key={sc}><td>{sc}</td>{systems.map((s) => <td key={s}>{pct(rep.metrics[s].scenarios[sc]?.accuracy)}</td>)}</tr>)}
          </tbody></table>
          <h3>External systems</h3>
          <table><tbody>{rep.external_systems.map((e) => <tr key={e.system}><td>{e.system}</td><td>{e.executed ? "executed" : "not executed"}</td><td>{e.reason}</td></tr>)}</tbody></table>
        </>
      )}
    </>
  );
}
