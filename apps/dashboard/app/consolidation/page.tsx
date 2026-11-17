import { Badge, Empty, ErrorBox, Header } from "@/components/ui";
import { USER_ID, api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Run = { run_id: string; ts: string; mode: string; rolled_back_at: string | null; created: number; near_duplicates: number; alias_merges: number; clusters: number; examined: number };

export default async function Consolidation() {
  const r = await api<Run[]>("/v1/consolidation/runs", { query: { user_id: USER_ID } });
  return (
    <>
      <Header title="Consolidation activity" sub="Each run only adds derived summaries and links; originals are untouched. Runs can be rolled back through the API." />
      {!r.ok ? <ErrorBox message={r.error} /> : r.data.length === 0 ? <Empty>No consolidation runs yet. POST /v1/consolidate to start one.</Empty> : (
        <table><thead><tr><th>Run</th><th>Time</th><th>Mode</th><th>Examined</th><th>Summaries</th><th>Near-dups</th><th>Alias merges</th><th>Clusters</th></tr></thead><tbody>
          {r.data.map((x) => (
            <tr key={x.run_id}>
              <td className="mono">{x.run_id}{x.rolled_back_at && <> <Badge tone="warn">rolled back</Badge></>}</td>
              <td className="mono">{x.ts.slice(0, 19)}</td><td>{x.mode}</td><td>{x.examined}</td><td>{x.created}</td><td>{x.near_duplicates}</td><td>{x.alias_merges}</td><td>{x.clusters}</td>
            </tr>
          ))}
        </tbody></table>
      )}
    </>
  );
}
