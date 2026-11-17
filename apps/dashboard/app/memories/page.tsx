import { Badge, Empty, ErrorBox, Header } from "@/components/ui";
import { USER_ID, api } from "@/lib/api";

export const dynamic = "force-dynamic";

type Mem = { id: string; original_content: string; category: string; scope_level: string; created_at: string; effective_at: string | null; version: number; source_type: string; source_reliability: number; verification: string; derived: boolean; mention_count: number; importance: number };

export default async function Memories({ searchParams }: { searchParams: Promise<{ category?: string }> }) {
  const { category } = await searchParams;
  const r = await api<Mem[]>("/v1/memories", { query: { user_id: USER_ID, limit: "200", ...(category ? { category } : {}) } });
  return (
    <>
      <Header title="Memory explorer" sub={`Memories visible to ${USER_ID}. Originals are never altered by consolidation.`} />
      <p>
        Filter: <a href="/memories">all</a> · <a href="/memories?category=episodic">episodic</a> · <a href="/memories?category=semantic">semantic</a> · <a href="/memories?category=procedural">procedural</a>
      </p>
      {!r.ok ? <ErrorBox message={r.error} /> : r.data.length === 0 ? <Empty>No memories.</Empty> : (
        <table>
          <thead><tr><th>Content</th><th>Category</th><th>Source</th><th>Reliability</th><th>Created</th><th>v</th></tr></thead>
          <tbody>
            {r.data.map((m) => (
              <tr key={m.id}>
                <td>{m.original_content.slice(0, 240)}{m.derived && <> <Badge>derived</Badge></>}<div className="mono">{m.id}</div></td>
                <td>{m.category}<div className="mono">{m.scope_level}</div></td>
                <td>{m.source_type}<div><Badge tone={m.verification === "verified" ? "ok" : m.verification === "disputed" ? "bad" : undefined}>{m.verification}</Badge></div></td>
                <td>{m.source_reliability.toFixed(2)}</td>
                <td className="mono">{m.effective_at ? `eff ${m.effective_at.slice(0, 10)}` : m.created_at.slice(0, 19)}</td>
                <td>{m.version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
