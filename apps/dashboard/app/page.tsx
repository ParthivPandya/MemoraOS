import { Empty, ErrorBox, Header, Stat } from "@/components/ui";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Stats = {
  memories: number; derived_memories: number; sources: number; facts: number; recalls: number; unsupported_rate: number;
  memories_by_category: Record<string, number>; recalls_by_strategy: Record<string, number>;
  recall_latency_ms: { p50: number; p95: number }; mean_context_tokens: number; storage_bytes: number; schema_version: number; embedder: string;
};
type Health = { status: string; schema_version: number; audit_chain_valid: boolean; embedder: string; chat_provider: string | null };

export default async function Overview() {
  const [stats, health] = await Promise.all([api<Stats>("/v1/stats"), api<Health>("/v1/system/health")]);
  if (!stats.ok) return <><Header title="Overview" /><ErrorBox message={stats.error} /></>;
  const s = stats.data;
  return (
    <>
      <Header title="Overview" sub="Live numbers from the MemoraOS API. Nothing on this page is sample data." />
      <div className="grid">
        <Stat k="Memories" v={s.memories} />
        <Stat k="Derived (consolidated)" v={s.derived_memories} />
        <Stat k="Sources" v={s.sources} />
        <Stat k="Active facts" v={s.facts} />
        <Stat k="Recalls" v={s.recalls} />
        <Stat k="Unsupported-answer rate" v={`${(100 * s.unsupported_rate).toFixed(1)}%`} />
        <Stat k="Recall latency p50 / p95" v={`${s.recall_latency_ms.p50} / ${s.recall_latency_ms.p95} ms`} />
        <Stat k="Storage" v={`${(s.storage_bytes / 1024).toFixed(0)} KiB`} />
      </div>
      <h3>Memories by category</h3>
      {Object.keys(s.memories_by_category).length === 0 ? <Empty>No memories yet. Store one with the API or the Python SDK.</Empty> : (
        <table><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>
          {Object.entries(s.memories_by_category).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}
        </tbody></table>
      )}
      <h3>System health</h3>
      {health.ok ? (
        <table><tbody>
          <tr><td>Status</td><td>{health.data.status}</td></tr>
          <tr><td>Schema version</td><td>{health.data.schema_version}</td></tr>
          <tr><td>Audit hash chain</td><td>{health.data.audit_chain_valid ? "valid" : "BROKEN"}</td></tr>
          <tr><td>Embedder</td><td className="mono">{health.data.embedder}</td></tr>
          <tr><td>Chat provider</td><td className="mono">{health.data.chat_provider ?? "none (extractive answers)"}</td></tr>
        </tbody></table>
      ) : <ErrorBox message={health.error} />}
    </>
  );
}
